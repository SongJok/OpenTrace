"""企业 AI 工作台的主链路与隔离合约。"""

from pathlib import Path
from types import SimpleNamespace

from gateway.api_gateway.main import app
from services.enterprise_workbench import build_enterprise_readiness

ROOT = Path(__file__).resolve().parents[1]


def _project(*, instructions: str = "", data_source_ids: list[str] | None = None):
    return SimpleNamespace(
        instructions=instructions,
        data_source_ids=data_source_ids or [],
    )


def test_workbench_api_is_exposed_on_v2_main_path() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v2/workbench/overview" in paths
    operation = paths["/api/v2/workbench/overview"]["get"]
    assert operation["tags"] == ["enterprise-workbench"]
    assert any(parameter["name"] == "recent_limit" for parameter in operation["parameters"])
    assert any(parameter["name"] == "attention_limit" for parameter in operation["parameters"])


def test_enterprise_readiness_is_explainable_and_actionable() -> None:
    result = build_enterprise_readiness(
        projects=[],
        profiles=[],
        goals=[],
        data_sources=[],
        knowledge_space_count=0,
        published_knowledge_count=0,
        active_task_count=0,
        active_alert_count=0,
        pending_approval_count=2,
        critical_alert_count=1,
        failed_response_count=1,
        knowledge_health={"score": 80, "status": "attention"},
    )
    assert result["status"] == "foundation"
    assert set(result["dimensions"]) == {
        "context",
        "knowledge",
        "data",
        "automation",
        "governance",
    }
    blocker_codes = {item["code"] for item in result["blockers"]}
    assert "project_context_missing" in blocker_codes
    assert "company_knowledge_missing" in blocker_codes
    assert "enterprise_data_missing" in blocker_codes
    assert all(item["route"].startswith("/") for item in result["blockers"])


def test_enterprise_readiness_rewards_governed_company_context() -> None:
    result = build_enterprise_readiness(
        projects=[_project(instructions="遵循公司指标口径", data_source_ids=["ds-1"])],
        profiles=[SimpleNamespace(built_in=False)],
        goals=[SimpleNamespace(status="in_progress")],
        data_sources=[SimpleNamespace(status="active")],
        knowledge_space_count=2,
        published_knowledge_count=18,
        active_task_count=1,
        active_alert_count=1,
        pending_approval_count=0,
        critical_alert_count=0,
        failed_response_count=0,
        knowledge_health={"score": 100, "status": "healthy"},
    )
    assert result["score"] == 100
    assert result["status"] == "ready"
    assert result["blockers"] == []


def test_workbench_queries_keep_user_tenant_and_workspace_boundaries() -> None:
    source = (ROOT / "services/enterprise_workbench.py").read_text(encoding="utf-8")
    for model in (
        "Project",
        "AssistantProfile",
        "GoalRun",
        "ResponseRecord",
        "TaskDefinition",
        "AlertRule",
        "KnowledgeSource",
    ):
        assert f"{model}.tenant_id == tenant_id" in source
        assert f"{model}.workspace_id == workspace_id" in source
    for model in (
        "Project",
        "AssistantProfile",
        "GoalRun",
        "ResponseRecord",
        "TaskDefinition",
        "AlertRule",
    ):
        assert f"{model}.user_id == user.id" in source
    assert "accessible_data_sources_statement" in source
    assert "accessible_source_predicate" in source
    assert "resolve_access_context" in source
    assert "knowledge_governance_health" in source


def test_workbench_is_a_projection_not_a_second_execution_plane() -> None:
    source = (ROOT / "services/enterprise_workbench.py").read_text(encoding="utf-8")
    assert "Redis" in source
    assert "create_response" not in source
    assert "background" not in source
    assert "db.commit" not in source
    assert "db.add" not in source


def test_workbench_attention_queue_has_a_bounded_enterprise_limit() -> None:
    source = (ROOT / "services/enterprise_workbench.py").read_text(encoding="utf-8")
    assert "attention_limit = max(5, min(attention_limit, 100))" in source
    assert "attention_items = _sort_by_created_at(attention_items)[:attention_limit]" in source
