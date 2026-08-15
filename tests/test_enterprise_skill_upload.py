from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request

from data_agent.contracts import DataSourceDecision
from gateway.api_gateway.main import app
from gateway.api_gateway.routers import skills
from gateway.api_gateway.routers.skills import list_company_skills
from infra.storage.models import EnterpriseSkill
from kernel.agent_loop.contracts import (
    EvidenceRequirement,
    ExecutionPlan,
    InformationSource,
    IntentPlan,
    PlanningDecision,
)
from kernel.agent_loop.evidence import ResponseEvidenceLedger
from kernel.agent_loop.intent_policy import apply_enterprise_intent_policy
from kernel.agent_loop.runner import AgentLoop
from skills import company
from skills.company import (
    CompanySkillUploadFile,
    retrieve_company_skills,
    validate_company_skill_package,
)

ROOT = Path(__file__).resolve().parents[1]


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/skills/company",
            "headers": [],
        }
    )


def _skill_md() -> str:
    return """---
name: 订单线上业务字典
description: 解释线上订单流程、表结构、核心注释与每个字段的业务逻辑。
version: 2.3.1
use_cases:
  - 回答订单状态和字段口径
---

# 订单线上业务字典

## 业务过程

订单支付后必须先通过风控，再进入履约；退款完成后不得重新发货。

## 表结构

`orders.order_status` 是订单状态，PAID 表示已支付但不代表已经发货。
"""


def _package_files() -> list[CompanySkillUploadFile]:
    return [
        CompanySkillUploadFile(
            path="order-skill/SKILL.md",
            content=_skill_md().encode(),
            content_type="text/markdown",
        ),
        CompanySkillUploadFile(
            path="order-skill/references/schema.sql",
            content=(
                "CREATE TABLE orders (order_status varchar(32));\n"
                "-- order_status=PAID 仅表示支付成功，履约状态以 fulfillment_status 为准。\n"
            ).encode(),
            content_type="application/sql",
        ),
    ]


def test_enterprise_skill_is_durable_and_tenant_scoped() -> None:
    assert EnterpriseSkill.__tablename__ == "enterprise_skills"
    assert {
        "tenant_id",
        "workspace_id",
        "runtime_id",
        "instructions",
        "source_digest",
        "source_files",
        "classification",
        "status",
        "published_by",
    }.issubset(EnterpriseSkill.__table__.columns.keys())


def test_uploaded_package_preserves_pre_distilled_business_logic_without_rewriting() -> None:
    package = validate_company_skill_package(
        [
            *_package_files(),
            CompanySkillUploadFile(path="order-skill/.DS_Store", content=b"finder metadata"),
        ]
    )

    assert package.name == "order-skill"
    assert package.version == "2.3.1"
    assert package.source_digest
    assert "PAID 表示已支付但不代表已经发货" in package.instructions
    schema = next(item for item in package.files if item["path"] == "references/schema.sql")
    assert "履约状态以 fulfillment_status 为准" in schema["content"]
    assert company.public_source_files(package.files) == [
        {key: item[key] for key in ("path", "sha256", "size", "content_type")}
        for item in package.files
    ]
    assert all("content" not in item for item in company.public_source_files(package.files))
    assert all(item["path"] != ".DS_Store" for item in package.files)


def test_real_world_folder_without_frontmatter_uses_directory_name_and_stays_inert() -> None:
    package = validate_company_skill_package(
        [
            CompanySkillUploadFile(
                path="php_table_schema/SKILL.md",
                content=(
                    "# PHP 项目表结构梳理（php_table_schema）\n\n"
                    "为没有 SQL 迁移文件的 PHP 项目梳理表结构和字段业务逻辑。\n\n"
                    "## 何时使用\n\n- 用户询问 PHP 表结构\n"
                ).encode(),
            ),
            CompanySkillUploadFile(
                path="php_table_schema/references/scanner.py",
                content=b"print('this uploaded reference must never execute')\n",
                content_type="text/x-python",
            ),
        ]
    )

    assert package.name == "php_table_schema"
    assert package.version == "1.0.0"
    assert package.description.startswith("为没有 SQL 迁移文件")
    assert package.use_cases == ["用户询问 PHP 表结构"]
    assert "print('this uploaded reference must never execute')" in next(
        item["content"] for item in package.files if item["path"].endswith("scanner.py")
    )


@pytest.mark.parametrize(
    ("files", "error"),
    [
        (
            [CompanySkillUploadFile(path="readme.md", content=b"plain readme")],
            "company_skill_requires_exactly_one_skill_md",
        ),
        (
            [CompanySkillUploadFile(path="../SKILL.md", content=_skill_md().encode())],
            "company_skill_invalid_path",
        ),
        (
            [
                CompanySkillUploadFile(
                    path="SKILL.md",
                    content=(_skill_md() + "\n-----BEGIN PRIVATE KEY-----\nsecret").encode(),
                )
            ],
            "company_skill_secret_detected",
        ),
    ],
)
def test_uploaded_package_fails_closed_for_invalid_or_sensitive_content(files, error) -> None:
    with pytest.raises(ValueError, match=error):
        validate_company_skill_package(files)


def test_company_skill_package_is_projected_to_tenant_scoped_local_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(skills.settings, "skillhub_local_mirror_dir", str(tmp_path / "mirror"))
    package = validate_company_skill_package(_package_files())
    row = SimpleNamespace(
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        runtime_id="company-local@2.3.1",
        source_digest=package.source_digest,
        name=package.name,
        description=package.description,
        value_summary=package.description,
        instructions=package.instructions,
        source_files=package.files,
        classification="internal",
    )

    assert skills._ensure_enterprise_skill_local(row) is True
    mirrored = tmp_path / "mirror" / "company"
    assert len(list(mirrored.rglob("SKILL.md"))) == 1
    schema_files = list(mirrored.rglob("schema.sql"))
    assert len(schema_files) == 1
    assert "fulfillment_status" in schema_files[0].read_text(encoding="utf-8")
    assert "tenant-1" not in schema_files[0].as_posix()


def test_company_skill_routes_replace_active_distillation_and_runtime_context_is_scoped() -> None:
    paths = app.openapi()["paths"]
    assert {"get"}.issubset(paths["/api/v1/skills/company"])
    assert {"post"}.issubset(paths["/api/v1/skills/company/upload"])
    assert {"delete"}.issubset(paths["/api/v1/skills/company/{skill_id}"])
    assert "/api/v1/skills/company/distill" not in paths
    context = (ROOT / "kernel/agent_loop/context.py").read_text(encoding="utf-8")
    router = (ROOT / "gateway/api_gateway/routers/skills.py").read_text(encoding="utf-8")
    retrieval = (ROOT / "skills/company.py").read_text(encoding="utf-8")
    for source in (router, retrieval):
        assert "EnterpriseSkill.tenant_id" in source
        assert "EnterpriseSkill.workspace_id" in source
        assert 'EnterpriseSkill.status == "published"' in source
        assert "classification_allows" in source
    assert "retrieve_company_skills" in context
    assert '"company_skills": company_skill_recall.manifest()' in context
    assert "公司 Skill + 企业大脑 + 个人记忆" in context
    assert "distill_enterprise_skill" not in router
    assert not (ROOT / "skills/distillation.py").exists()


@pytest.mark.asyncio
async def test_company_skill_list_filters_items_above_employee_clearance(monkeypatch) -> None:
    internal = SimpleNamespace(
        id="skill-1",
        runtime_id="company-internal@1.0.0",
        name="内部流程",
        description="",
        value_summary="",
        instructions="内部流程",
        source_files=[],
        use_cases=[],
        classification="internal",
        status="published",
        published_at=None,
    )
    confidential = SimpleNamespace(
        **{
            **internal.__dict__,
            "id": "skill-2",
            "runtime_id": "company-confidential@1.0.0",
            "name": "机密流程",
            "classification": "confidential",
        }
    )
    result = Mock()
    result.scalars.return_value.all.return_value = [internal, confidential]
    db = AsyncMock()
    db.execute.return_value = result
    monkeypatch.setattr(
        skills,
        "build_tenant_metadata",
        lambda *_args, **_kwargs: {"tenant_id": "tenant-1", "workspace_id": "workspace-1"},
    )
    monkeypatch.setattr(
        skills,
        "resolve_access_context",
        AsyncMock(return_value=SimpleNamespace(clearance="internal")),
    )

    response = await list_company_skills(
        request=_request(),
        current_user=SimpleNamespace(id="user-1", is_superuser=False),
        db=db,
    )

    assert [item["runtime_id"] for item in response["items"]] == [internal.runtime_id]
    assert response["items"][0]["execution_policy"] == "context_only"
    assert response["items"][0]["active_distillation"] is False


@pytest.mark.asyncio
async def test_company_skill_recall_returns_exact_field_logic_and_clearance(monkeypatch) -> None:
    package = validate_company_skill_package(_package_files())
    internal = SimpleNamespace(
        id="skill-1",
        runtime_id="company-skill-1@2.3.1",
        name=package.name,
        description=package.description,
        value_summary=package.description,
        instructions=package.instructions,
        source_digest=package.source_digest,
        source_files=package.files,
        use_cases=package.use_cases,
        classification="internal",
        status="published",
        published_at=datetime.now(UTC),
    )
    restricted = SimpleNamespace(
        **{
            **internal.__dict__,
            "id": "skill-2",
            "runtime_id": "company-skill-2@1.0.0",
            "name": "机密订单规则",
            "classification": "confidential",
        }
    )
    result = Mock()
    result.scalars.return_value.all.return_value = [internal, restricted]
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(id="user-1")
    db.execute.return_value = result
    monkeypatch.setattr(
        company,
        "resolve_access_context",
        AsyncMock(return_value=SimpleNamespace(clearance="internal")),
    )

    recall = await retrieve_company_skills(
        db,
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        query="orders.order_status 的 PAID 到底代表什么？",
    )

    assert recall.manifest()["answer_context_available"] is True
    assert [item["id"] for item in recall.skills] == ["skill-1"]
    assert "PAID 仅表示支付成功" in "\n".join(recall.entries)
    assert "不要要求用户重复确认" in recall.prompt
    assert "实时记录" in recall.prompt
    sql = str(db.execute.await_args.args[0])
    assert "enterprise_skills.tenant_id" in sql
    assert "enterprise_skills.workspace_id" in sql


@pytest.mark.asyncio
async def test_data_agent_receives_matched_company_skill_business_semantics(monkeypatch) -> None:
    from data_agent.adapters.opentrace.source_resolution import OpenTraceSourceResolver
    from infra.storage import database

    session = SimpleNamespace(is_temporary=False, assistant_profile_id=None)

    class ScopeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalar(self, _statement):
            return session

    async def resolve(_self, **kwargs):
        return DataSourceDecision(
            status="selected",
            question=str(kwargs["question"]),
            selected_data_source_id="trusted-source",
            selected_data_source_name="认证交易数仓",
            confidence=0.99,
            reason="唯一可信数据源",
        )

    recall = company.CompanySkillRecall(
        entries=("## Skill：订单业务\norders.order_status=PAID 仅表示支付成功。",),
        skills=(
            {
                "id": "skill-1",
                "runtime_id": "company-skill-1@2.3.1",
                "source_digest": "a" * 64,
                "matched_paths": ["references/schema.sql"],
            },
        ),
        top_score=0.9,
    )
    monkeypatch.setattr(database, "AsyncSessionLocal", ScopeSession)
    monkeypatch.setattr(OpenTraceSourceResolver, "resolve", resolve)
    monkeypatch.setattr(company, "retrieve_company_skills", AsyncMock(return_value=recall))
    response = SimpleNamespace(
        id="response-1",
        conversation_id="conversation-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        request_payload={"input": "查询已支付订单", "opentrace": {}},
    )

    params, error = await AgentLoop._hydrate_agent_params(
        response=response,
        agent_name="data",
        params={},
        query="查询 order_status=PAID 的订单数",
    )

    assert error is None
    assert "PAID 仅表示支付成功" in params["clarify_context"]
    assert params["company_skill_evidence"][0]["id"] == "skill-1"
    assert params["data_source_id"] == "trusted-source"


def test_company_skill_is_a_first_class_intent_and_evidence_source() -> None:
    manifest = {
        "company_skills": {
            "answer_context_available": True,
            "skills": [
                {
                    "id": "skill-1",
                    "runtime_id": "company-skill-1@2.3.1",
                    "name": "订单线上业务字典",
                    "version": "2.3.1",
                    "classification": "internal",
                    "source_digest": "a" * 64,
                    "top_score": 0.9,
                    "matched_paths": ["SKILL.md"],
                }
            ],
        }
    }
    decision = PlanningDecision(
        intent=IntentPlan(goal="解释订单状态"),
        execution_plan=ExecutionPlan(goal="解释订单状态"),
    )
    governed = apply_enterprise_intent_policy(
        decision,
        query="order_status 是什么",
        context_manifest=manifest,
        tool_specs=[],
    )
    assert governed.intent.information_sources == (InformationSource.COMPANY_SKILL,)
    assert governed.intent.evidence_requirements == (EvidenceRequirement.COMPANY_SKILL_CONTEXT,)
    ledger = ResponseEvidenceLedger.from_context(
        governed.intent,
        context_manifest=manifest,
        memory_ids=[],
    )
    assert any(item.source == InformationSource.COMPANY_SKILL for item in ledger.entries.values())

    unclear = PlanningDecision(
        intent=IntentPlan(
            goal="解释订单状态",
            ambiguity="capability_unavailable",
            clarification_question="请重新提供字段说明。",
        ),
        execution_plan=ExecutionPlan(goal="解释订单状态"),
    )
    grounded = AgentLoop._apply_grounded_context_policy(unclear, context_manifest=manifest)
    assert grounded.intent.clarification_question is None
    assert grounded.intent.ambiguity is None
