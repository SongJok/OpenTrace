"""企业 AI 工作台的主链路与隔离合约。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from gateway.api_gateway.main import app
from services.enterprise_workbench import build_enterprise_readiness, build_workbench_activity

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
    assert "enterprise_cognition_missing" in blocker_codes
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
        cognitive_entity_count=2,
        published_company_context=True,
    )
    assert result["score"] == 100
    assert result["status"] == "ready"
    assert result["blockers"] == []


def test_workbench_activity_deduplicates_conversations_and_exposes_next_action() -> None:
    now = datetime(2026, 8, 5, 8, tzinfo=UTC)
    sessions = [
        SimpleNamespace(
            id="conversation-1",
            title="New conversation",
            display_title="经营月报复核",
            project_id="project-1",
        ),
        SimpleNamespace(
            id="conversation-2",
            title="异常指标排查",
            display_title=None,
            project_id=None,
        ),
    ]
    responses = [
        SimpleNamespace(
            id="response-latest",
            conversation_id="conversation-1",
            goal_id="goal-1",
            status="requires_action",
            request_payload={"input": "生成本月经营月报"},
            attempt_count=1,
            max_attempts=3,
            updated_at=now,
        ),
        SimpleNamespace(
            id="response-older",
            conversation_id="conversation-1",
            goal_id=None,
            status="completed",
            request_payload={"input": "整理经营口径"},
            attempt_count=1,
            max_attempts=3,
            updated_at=now - timedelta(hours=1),
        ),
        SimpleNamespace(
            id="response-failed",
            conversation_id="conversation-2",
            goal_id=None,
            status="failed",
            request_payload={"input": "排查现金流异常"},
            attempt_count=3,
            max_attempts=3,
            updated_at=now - timedelta(minutes=10),
        ),
    ]
    goals = [
        SimpleNamespace(
            id="goal-1",
            conversation_id="conversation-1",
            response_id="response-latest",
            project_id="project-1",
            objective="持续交付经营月报",
            status="in_progress",
            current_step=2,
            updated_at=now,
        ),
        SimpleNamespace(
            id="goal-standalone",
            conversation_id=None,
            response_id=None,
            project_id=None,
            objective="建立季度复盘机制",
            status="paused",
            current_step=1,
            updated_at=now - timedelta(hours=2),
        ),
    ]

    result = build_workbench_activity(
        responses=responses,
        goals=goals,
        sessions=sessions,
        projects=[SimpleNamespace(id="project-1", name="经营分析")],
        limit=10,
    )

    assert [item["id"] for item in result] == [
        "goal-1",
        "response-failed",
        "goal-standalone",
    ]
    assert result[0] == {
        "id": "goal-1",
        "type": "goal",
        "status": "requires_action",
        "title": "经营月报复核",
        "description": "Goal · 检查点 2",
        "route": "/chat?conversation=conversation-1",
        "action": "approval",
        "action_label": "处理审批",
        "conversation_id": "conversation-1",
        "response_id": "response-latest",
        "goal_id": "goal-1",
        "project_id": "project-1",
        "project_name": "经营分析",
        "created_at": now.isoformat(),
    }
    assert result[1]["action"] == "retry"
    assert result[1]["route"] == "/chat?conversation=conversation-2"
    assert result[2]["action"] == "resume"
    assert result[2]["route"] == "/work?tab=goals"


def test_workbench_queries_keep_user_tenant_and_workspace_boundaries() -> None:
    source = (ROOT / "services/enterprise_workbench.py").read_text(encoding="utf-8")
    for model in (
        "Project",
        "AssistantProfile",
        "GoalRun",
        "ResponseRecord",
        "TaskDefinition",
        "AlertRule",
        "CalendarEvent",
        "KnowledgeSource",
        "ChatSession",
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
        "CalendarEvent",
    ):
        assert f"{model}.user_id == user.id" in source
    assert "accessible_data_sources_statement" in source
    assert "accessible_source_predicate" in source
    assert "resolve_access_context" in source
    assert "knowledge_governance_health" in source
    assert "ChatSession.archived_at.is_(None)" in source
    assert "ChatSession.is_temporary.is_(False)" in source


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
    assert "candidate_limit = max(attention_limit, 50)" in source
    assert "rank_workbench_actions(attention_items, now=generated_at)[:attention_limit]" in source
    assert "focus_limit=min(attention_limit, 8)" in source
    assert "unacknowledged_alert_count" in source
    assert '"unacknowledged_alerts": unacknowledged_alert_count' in source
