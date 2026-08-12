"""公司与部门认知底座的模型、API、上下文和产品合约。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.api_gateway.main import app
from gateway.api_gateway.routers.enterprise_admin import CognitiveDraftInput, CognitiveEntityInput
from infra.storage.models import EnterpriseCognitiveEntity, EnterpriseCognitiveVersion
from services.enterprise_cognition import (
    EnterpriseContextBundle,
    _render_context_prompt,
)

ROOT = Path(__file__).resolve().parents[1]


def test_cognitive_models_are_scoped_versioned_and_governed() -> None:
    assert EnterpriseCognitiveEntity.__tablename__ == "enterprise_cognitive_entities"
    assert EnterpriseCognitiveVersion.__tablename__ == "enterprise_cognitive_versions"
    assert {
        "tenant_id",
        "workspace_id",
        "entity_type",
        "entity_key",
        "directory_principal_id",
        "knowledge_space_id",
        "status",
        "created_by",
    }.issubset(EnterpriseCognitiveEntity.__table__.columns.keys())
    assert {
        "entity_id",
        "tenant_id",
        "workspace_id",
        "version",
        "status",
        "classification",
        "summary",
        "mission",
        "vision",
        "responsibilities",
        "terminology",
        "source_refs",
        "effective_from",
        "effective_to",
        "review_due_at",
        "published_by",
        "published_at",
    }.issubset(EnterpriseCognitiveVersion.__table__.columns.keys())


def test_cognition_admin_and_employee_context_apis_are_exposed() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/admin/enterprise/cognition/entities": {"get", "post"},
        "/api/v1/admin/enterprise/cognition/entities/{entity_id}/draft": {"put"},
        "/api/v1/admin/enterprise/cognition/entities/{entity_id}/versions": {"get"},
        "/api/v1/admin/enterprise/cognition/entities/{entity_id}/publish": {"post"},
        "/api/v1/admin/enterprise/cognition/entities/{entity_id}/archive": {"post"},
        "/api/v2/enterprise-context/current": {"get"},
    }
    for path, methods in expected.items():
        assert methods.issubset(paths[path])
    assert "201" in paths["/api/v1/admin/enterprise/cognition/entities"]["post"]["responses"]


def test_cognitive_requests_require_department_binding_and_bounded_content() -> None:
    department = CognitiveEntityInput(
        entity_type="department",
        display_name="财务部",
        department_external_id="finance",
        knowledge_space_id="space-1",
    )
    assert department.department_external_id == "finance"
    draft = CognitiveDraftInput(
        summary="负责公司财务核算、预算和资金治理。",
        mission="让经营决策建立在可靠财务事实之上。",
        terminology={"GMV": "成交总额"},
        source_refs=["knowledge:finance-charter"],
    )
    assert draft.classification == "internal"
    assert draft.terminology["GMV"] == "成交总额"
    with pytest.raises(ValidationError):
        CognitiveEntityInput(entity_type="company", display_name="")


def test_enterprise_context_prompt_is_compact_and_query_adaptive() -> None:
    entity = {
        "entity_id": "company-1",
        "entity_type": "company",
        "entity_key": "org-a",
        "display_name": "示例科技",
        "knowledge_space_id": "space-company",
        "version_id": "version-2",
        "version": 2,
        "classification": "internal",
        "summary": "面向制造企业提供智能运营平台。",
        "mission": "让企业运营更可靠。",
        "vision": "成为最懂客户业务的技术伙伴。",
        "values": ["客户价值优先", "以事实决策"],
        "responsibilities": ["建设平台产品"],
        "products_services": ["企业提问系统"],
        "operating_principles": ["重要结论必须可追溯"],
        "terminology": {"有效客户": "过去 90 天有付费订单的客户"},
        "key_contacts": ["产品负责人：张三"],
    }
    generic = _render_context_prompt([entity], query="帮我写一段欢迎语", max_chars=6000)
    detailed = _render_context_prompt([entity], query="公司的有效客户口径是什么", max_chars=6000)
    assert "面向制造企业提供智能运营平台" in generic
    assert "有效客户=" not in generic
    assert "有效客户=过去 90 天有付费订单的客户" in detailed
    assert "必须检索绑定的企业知识并保留引用" in detailed
    assert len(_render_context_prompt([entity], query="公司制度", max_chars=120)) == 120


def test_context_manifest_keeps_version_and_grounding_provenance() -> None:
    bundle = EnterpriseContextBundle(
        prompt="企业基础认知",
        entities=[
            {
                "entity_id": "company-1",
                "entity_type": "company",
                "entity_key": "org-a",
                "version_id": "version-2",
                "version": 2,
                "classification": "internal",
                "knowledge_space_id": "space-company",
            }
        ],
        knowledge_space_ids=["space-company"],
        requires_grounding=True,
    )
    manifest = bundle.manifest()
    assert manifest["entities"][0]["version_id"] == "version-2"
    assert manifest["knowledge_space_ids"] == ["space-company"]
    assert manifest["requires_grounding"] is True


def test_responses_main_path_injects_cognition_and_forces_governed_rag() -> None:
    context_source = (ROOT / "kernel/agent_loop/context.py").read_text(encoding="utf-8")
    runner_source = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")
    responses_source = (ROOT / "gateway/api_gateway/routers/responses.py").read_text(
        encoding="utf-8"
    )
    assert "load_enterprise_context" in context_source
    assert context_source.index("enterprise_context.prompt") < context_source.index("助手角色")
    assert 'context_manifest.get("enterprise_context")' in runner_source
    assert 'selected_capabilities.add("rag")' in runner_source
    assert "enterprise_grounding_required" in runner_source
    assert 'hydrated.pop("knowledge_space_ids", None)' in runner_source
    assert 'hydrated["enterprise_grounding_required"] = True' in runner_source
    assert '"knowledge_space_ids": list(' in runner_source
    assert '"org_id": org_id' in responses_source


def test_cognition_service_keeps_user_tenant_workspace_and_department_boundaries() -> None:
    source = (ROOT / "services/enterprise_cognition.py").read_text(encoding="utf-8")
    for model in (
        "EnterpriseCognitiveEntity",
        "EnterpriseCognitiveVersion",
        "EnterpriseDirectoryMembership",
        "EnterpriseDirectoryPrincipal",
    ):
        assert f"{model}.tenant_id == tenant_id" in source
        assert f"{model}.workspace_id == workspace_id" in source
    assert "EnterpriseDirectoryMembership.user_id == user_id" in source
    assert "classification_allows" in source
    assert "accessible_space_ids = set(access.accessible_space_ids)" in source
    assert "effective_from" in source
    assert "effective_to" in source
    assert "with_for_update" in source


def test_r0007_migration_and_frontend_governance_surface_are_present() -> None:
    migration = (ROOT / "alembic/versions/r0007_enterprise_cognition.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "r0007_enterprise_cognition"' in migration
    assert 'down_revision = "r0006_calendar_events"' in migration
    assert "uq_enterprise_cognitive_published_entity" in migration
    assert "enterprise_cognitive_entities" in migration
    assert "enterprise_cognitive_versions" in migration
    page = (ROOT / "frontend/src/pages/CompanyBrainPage.tsx").read_text(encoding="utf-8")
    client = (ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert "企业大脑" in page
    assert "企业大脑" in page
    assert "apiSaveCompanyBrainDraft" in page
    assert "apiPublishCompanyBrainDraft" in page
    assert "/admin/company/brain/draft" in client
