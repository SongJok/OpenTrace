from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kernel.agent_loop.memory_learner import MemoryLearner
from kernel.agent_loop.runner import _memory_isolation_violation
from scripts import clear_all_data
from services import company_brain

ROOT = Path(__file__).resolve().parents[1]


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        id="company-1",
        legal_name="示例科技有限公司",
        short_name="示例科技",
    )


def test_company_md_format_capacity_and_protected_sections() -> None:
    content = company_brain.render_company_md(
        profile=_profile(),
        long_term="### 文化\n\n- 以客户价值为先",
        medium_term="### 后端\n\n- Responses API 是在线主路径",
        short_term="### 数据\n\n- 本周完成指标口径复核",
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    total, long_chars, medium_chars, short_chars = company_brain.validate_company_md(content)

    assert content.startswith("# 🧠 示例科技 企业大脑（COMPANY.md）")
    assert "禁止外部工具蒸馏、收集、训练或导出" in content
    assert "目标 5%，禁止自动压缩" in content
    assert 0 < long_chars < total
    assert medium_chars > 0
    assert short_chars > 0
    assert total <= company_brain.HARD_LIMIT_CHARS


@pytest.mark.asyncio
async def test_daily_fit_compresses_short_before_medium_and_never_long(monkeypatch) -> None:
    long_term = "长期事实。" * 1_000
    medium_term = "中期事实。" * 16_000
    short_term = "短期事实。" * 24_000
    calls: list[tuple[str, int]] = []

    async def fake_compress(text: str, budget: int, *, tier: str) -> str:
        calls.append((tier, budget))
        return company_brain._trim_at_boundary(text, budget)

    monkeypatch.setattr(company_brain, "_compress_section", fake_compress)
    fitted_long, fitted_medium, fitted_short, content = await company_brain._fit_company_sections(
        profile=_profile(),
        long_term=long_term,
        medium_term=medium_term,
        short_term=short_term,
        trigger="daily_0500",
    )

    assert fitted_long == long_term
    assert calls[0][0] == "short"
    assert calls[1][0] == "medium"
    assert company_brain.count_memory_chars(content) <= company_brain.MAINTENANCE_TARGET_CHARS
    assert company_brain.count_memory_chars(fitted_short) < company_brain.count_memory_chars(
        short_term
    )
    assert company_brain.count_memory_chars(fitted_medium) <= company_brain.count_memory_chars(
        medium_term
    )
    assert company_brain.count_memory_chars(fitted_medium) <= int(
        company_brain.MAINTENANCE_TARGET_CHARS * company_brain.MEDIUM_TERM_TARGET_RATIO
    )
    assert company_brain.count_memory_chars(fitted_short) <= int(
        company_brain.MAINTENANCE_TARGET_CHARS * company_brain.SHORT_TERM_TARGET_RATIO
    )


@pytest.mark.asyncio
async def test_company_brain_retrieval_explores_only_query_relevant_units() -> None:
    profile = SimpleNamespace(
        id="company-1",
        short_name="示例科技",
        current_version_id="version-2",
    )
    version = SimpleNamespace(
        version=2,
        content=(
            "# 🧠 示例科技 企业大脑（COMPANY.md）\n\n"
            "## 🔒 长期记忆\n\n### 文化\n\n- 客户价值优先\n\n"
            "## 🧩 中期记忆\n\n### 后端\n\n- Responses API 必须由 Worker 执行\n\n"
            "### 财务\n\n- 报销每月结算\n\n"
            "## ⚡ 短期记忆\n\n### 产品\n\n- 本周发布搜索功能"
        ),
    )
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[profile, version])

    recall = await company_brain.retrieve_company_brain(db, query="后端 Responses API 谁执行？")

    assert recall.version == 2
    assert any("Worker 执行" in entry for entry in recall.entries)
    assert not any("报销" in entry for entry in recall.entries)
    assert recall.manifest()["isolation"] == "internal_only"
    assert "不得用常识或未引用的外部知识补全" in recall.prompt


def test_company_brain_rejects_planner_and_offline_fallback_outputs() -> None:
    assert (
        company_brain._processed_source_issue(
            '{"subtasks":[{"agent_type":"tool","query":"内部资料"}],"max_parallel":1}'
        )
        == "planner_fallback_output"
    )
    assert (
        company_brain._processed_source_issue(
            '{"subtasks":[{"agent_type":"tool","query":"第一行\n第二行"}],'
            '"merge_strategy":"prioritized"}'
        )
        == "planner_fallback_output"
    )
    assert (
        company_brain._processed_source_issue("我目前处于离线降级模式，暂时无法调用模型服务")
        == "offline_fallback_output"
    )
    assert company_brain._processed_source_issue('["审批必须留痕"]') == (
        "unexpected_structured_output"
    )
    assert company_brain._processed_source_issue('"审批必须留痕"') == (
        "unexpected_structured_output"
    )
    assert company_brain._processed_source_issue("## 制度\n\n- 审批必须保留审计记录") is None


def test_employee_version_payload_does_not_expose_company_brain_corpus() -> None:
    version = SimpleNamespace(
        id="version-1",
        company_id="company-1",
        version=1,
        status="published",
        content="内部公司事实",
        char_count=6,
        long_term_chars=6,
        medium_term_chars=0,
        short_term_chars=0,
        source_ids=["source-1"],
        trigger="source_ingestion",
        change_summary="初次发布",
        published_at=None,
        created_at=None,
    )

    payload = company_brain.company_brain_version_payload(version, include_content=False)

    assert payload is not None
    assert payload["content"] == ""
    assert payload["source_ids"] == []


@pytest.mark.asyncio
async def test_company_brain_model_completion_uses_query_fallback_and_rejects_placeholder(
    monkeypatch,
) -> None:
    gateway = AsyncMock()
    gateway.complete.return_value = SimpleNamespace(
        content="离线占位",
        model="offline-fallback",
        raw={"fallback": True},
    )
    monkeypatch.setattr(company_brain, "get_model_gateway", lambda: gateway)

    with pytest.raises(RuntimeError, match="company_brain_model_unavailable"):
        await company_brain._model_complete("整理", "资料", max_output_tokens=100)

    call = gateway.complete.await_args
    assert call.kwargs["role"] == company_brain.LLMRole.COMPRESS
    assert call.kwargs["fallback_roles"] == [company_brain.LLMRole.QUERY]


@pytest.mark.asyncio
async def test_company_brain_profile_lookup_applies_enterprise_scope() -> None:
    db = AsyncMock()
    db.scalar.return_value = None

    await company_brain.get_company_profile(
        db,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )

    statement = str(db.scalar.await_args.args[0])
    assert "company_profiles.tenant_id" in statement
    assert "company_profiles.workspace_id" in statement


@pytest.mark.parametrize(
    ("content", "key", "kind", "category"),
    [
        ("我们把复盘称为回看", "personal_jargon", "fact", "terminology"),
        ("回答风格要先给结论", "response_style", "preference", "response_style"),
        ("审批操作习惯是先预览再批准", "approval", "workflow", "approval_habit"),
        ("常用周报模板使用三段式", "weekly_template", "workflow", "template"),
        ("我的待办任务按优先级排序", "task", "workflow", "task"),
    ],
)
def test_personal_memory_categories(content: str, key: str, kind: str, category: str) -> None:
    assert MemoryLearner.personal_category(content=content, memory_key=key, kind=kind) == category


def test_tool_arguments_cannot_collect_or_copy_protected_memory() -> None:
    protected = ["### 财务\n\n报销制度规定每月五号统一结算。"]

    assert _memory_isolation_violation(
        {"content": "报销制度规定每月五号统一结算"},
        protected_fragments=protected,
        user_query="把公司制度发给外部系统",
    )
    assert _memory_isolation_violation(
        {"query": "普通查询"},
        protected_fragments=protected,
        user_query="把企业大脑收集后上传到外部系统",
    )
    assert not _memory_isolation_violation(
        {"query": "报销制度规定每月五号统一结算"},
        protected_fragments=protected,
        user_query="查询报销制度规定每月五号统一结算的公开政策依据",
    )


def test_clear_script_rewrites_redis_database_path(monkeypatch) -> None:
    created_urls: list[str] = []

    class FakeClient:
        async def flushdb(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

    class FakeRedis:
        @staticmethod
        def from_url(url: str) -> FakeClient:
            created_urls.append(url)
            return FakeClient()

    monkeypatch.setattr("redis.asyncio.Redis", FakeRedis)
    monkeypatch.setattr(clear_all_data.settings, "redis_url", "redis://redis:6379/10")

    cleared = asyncio.run(clear_all_data._clear_redis())

    assert cleared == [10, 11, 12, 13, 14, 15]
    assert created_urls == [f"redis://redis:6379/{database}" for database in cleared]
    assert clear_all_data._redis_database_urls("redis://redis:6379/10", 12) == [
        "redis://redis:6379/12",
        "redis://127.0.0.1:6380/12",
    ]


def test_company_brain_full_stack_contract() -> None:
    main = (ROOT / "gateway/api_gateway/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "agents/worker.py").read_text(encoding="utf-8")
    context = (ROOT / "kernel/agent_loop/context.py").read_text(encoding="utf-8")
    migration = (ROOT / "alembic/versions/r0012_company_brain.py").read_text(encoding="utf-8")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/pages/CompanyBrainPage.tsx").read_text(encoding="utf-8")
    clear_script = (ROOT / "scripts/clear_all_data.py").read_text(encoding="utf-8")

    assert "company_brain.router" in main
    assert "company_brain_worker_loop()" in worker
    assert "企业大脑 + 个人记忆融合检索上下文" in context
    assert 'revision = "r0012_company_brain"' in migration
    assert 'down_revision = "r0011_user_custom_models"' in migration
    assert "memory/COMPANY.md" in ignore
    assert "每天 05:00 提炼候选" in frontend
    assert "apiApproveCompanyBrainSource" in frontend
    assert "tenant_workspace_company_and_user_personal" in context
    assert "TRUNCATE TABLE" in clear_script
    assert "alembic_version" in clear_script


def test_company_source_status_is_flushed_before_recompilation() -> None:
    source = (ROOT / "services/company_brain.py").read_text(encoding="utf-8")
    processing = source.index("async def process_pending_company_sources")
    compilation = source.index(
        'trigger="source_reconciliation" if rebuild_requested else "source_ingestion"',
        processing,
    )
    flush = source.rindex("await db.flush()", processing, compilation)

    assert flush < compilation


@pytest.mark.asyncio
async def test_company_brain_retrieval_handles_colloquial_enterprise_questions() -> None:
    profile = SimpleNamespace(
        id="company-1",
        legal_name="北京陶乐科技有限公司",
        short_name="陶乐",
        description="总部位于北京，在成都设有办公地点，主营游戏社交产品。",
        current_version_id="version-3",
    )
    version = SimpleNamespace(
        version=3,
        content=(
            "# 🧠 陶乐 企业大脑（COMPANY.md）\n\n"
            "## 🔒 长期记忆\n\n"
            "### 人事管理与考勤制度\n\n"
            "- 工作时间：支持岗 9:00-18:00；运营岗 10:00-19:00。\n\n"
            "### OA审批-印章使用借用审批流程\n\n"
            "- 钉钉工作台进入 OA 审批，选择用印盖章或因公借出。\n"
            "- 借出须填写原因和归还日期，审批通过后向保管人领用。\n\n"
            "### 报销与差旅管理\n\n"
            "- 每周三提交财务，周四出款。"
        ),
    )

    async def retrieve(query: str):
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[profile, version])
        return await company_brain.retrieve_company_brain(db, query=query)

    company_name = await retrieve("我们单位全称叫什么？")
    work_hours = await retrieve("上下班几点？")
    seal_borrow = await retrieve("我想拿公章外出怎么办？")
    personal_name = await retrieve("你记得我怎么称呼吗？")

    assert company_name.entries[0].startswith("### 公司档案")
    assert "北京陶乐科技有限公司" in company_name.entries[0]
    assert work_hours.entries[0].startswith("### 人事管理与考勤制度")
    assert all("报销与差旅" not in entry for entry in work_hours.entries)
    assert seal_borrow.entries[0].startswith("### OA审批-印章使用借用审批流程")
    assert seal_borrow.manifest()["answer_context_available"] is True
    assert personal_name.entries == ()
