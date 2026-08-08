"""企业工作台 Project 工作组合的确定性投影合约。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from services.workbench_portfolio import build_workbench_portfolio

ROOT = Path(__file__).resolve().parents[1]


def _project(project_id: str, name: str, *, instructions: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=project_id,
        name=name,
        description=f"{name}业务",
        instructions=instructions,
        data_source_ids=["database-1"] if instructions else [],
        updated_at=datetime(2026, 8, 7, tzinfo=UTC),
    )


def _response(
    response_id: str,
    conversation_id: str,
    status: str,
    now: datetime,
    *,
    goal_id: str | None = None,
    completed_at: datetime | None = None,
    error_message: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        conversation_id=conversation_id,
        goal_id=goal_id,
        status=status,
        request_payload={"input": f"处理 {response_id}"},
        error_message=error_message,
        updated_at=now,
        completed_at=completed_at,
    )


def test_portfolio_combines_project_work_and_selects_one_explainable_next_action() -> None:
    now = datetime(2026, 8, 8, 3, tzinfo=UTC)
    projects = [
        _project("project-1", "经营分析", instructions="按已审核经营口径输出"),
        _project("project-2", "客户运营"),
    ]
    sessions = [
        SimpleNamespace(
            id="conversation-1", project_id="project-1", display_title="经营月报", title=""
        ),
        SimpleNamespace(
            id="conversation-2", project_id="project-1", display_title="预算复核", title=""
        ),
        SimpleNamespace(id="conversation-3", project_id=None, display_title="临时分析", title=""),
    ]
    responses = [
        _response(
            "response-failed",
            "conversation-1",
            "failed",
            now - timedelta(hours=2),
            error_message="数据源连接中断",
        ),
        _response(
            "response-approval", "conversation-2", "requires_action", now - timedelta(hours=1)
        ),
        _response(
            "response-completed",
            "conversation-1",
            "completed",
            now - timedelta(hours=4),
            completed_at=now - timedelta(hours=4),
        ),
        _response(
            "response-unassigned", "conversation-3", "in_progress", now - timedelta(minutes=5)
        ),
        _response("response-old-failure", "conversation-1", "failed", now - timedelta(days=8)),
    ]
    goals = [
        SimpleNamespace(
            id="goal-1",
            project_id="project-1",
            conversation_id="conversation-2",
            objective="持续交付经营月报",
            status="in_progress",
            current_step=2,
            updated_at=now - timedelta(minutes=30),
        )
    ]
    pending_approvals = [
        (
            SimpleNamespace(
                response_id="response-approval",
                tool_name="create_scheduled_task",
                side_effect_level="write",
                created_at=now - timedelta(hours=1),
            ),
            "conversation-2",
        )
    ]
    tasks = [
        SimpleNamespace(
            id="task-1",
            project_id="project-1",
            status="active",
            title="经营日报",
            task_type="enterprise_report",
            next_run_at=now + timedelta(hours=2),
            updated_at=now,
        )
    ]
    alerts = [
        SimpleNamespace(
            id="rule-1",
            project_id="project-1",
            status="active",
            name="现金流监控",
            next_run_at=now + timedelta(hours=1),
            updated_at=now,
        )
    ]
    alert_events = [
        SimpleNamespace(
            id="event-1",
            rule_id="rule-1",
            severity="critical",
            summary="现金流低于安全线",
            created_at=now - timedelta(minutes=10),
        )
    ]

    result = build_workbench_portfolio(
        projects=projects,
        sessions=sessions,
        responses=responses,
        goals=goals,
        pending_approvals=pending_approvals,
        tasks=tasks,
        alerts=alerts,
        alert_events=alert_events,
        now=now,
    )

    assert result["window_days"] == 7
    assert [item["name"] for item in result["items"]] == [
        "经营分析",
        "未归入 Project",
        "客户运营",
    ]
    operating = result["items"][0]
    assert operating["status"] == "critical"
    assert operating["status_reason"] == "有 1 个关键业务预警未确认"
    assert operating["active_work"] == 1  # Goal 与 Response 共享同一会话，不重复计数。
    assert operating["pending_approvals"] == 1
    assert operating["failed_responses_7d"] == 1
    assert operating["delivered_turns_7d"] == 1
    assert operating["active_automations"] == 2
    assert operating["next_action"] == {
        "type": "alert",
        "label": "确认预警",
        "title": "现金流低于安全线",
        "description": "查看触发证据、当前值和规则口径后确认处置。",
        "route": "/alerts",
        "created_at": (now - timedelta(minutes=10)).isoformat(),
    }
    assert result["items"][1]["status"] == "attention"
    assert result["items"][1]["next_action"]["route"] == "/chat?conversation=conversation-3"
    assert result["items"][2]["status"] == "foundation"
    assert result["items"][2]["next_action"]["type"] == "setup"
    assert result["summary"] == {
        "projects": 2,
        "critical_projects": 1,
        "attention_projects": 1,
        "active_projects": 0,
        "active_work": 2,
        "pending_approvals": 1,
        "unacknowledged_alerts": 1,
        "delivered_turns_7d": 1,
        "unassigned_work": 1,
    }


def test_portfolio_routes_failed_work_back_to_the_exact_durable_conversation() -> None:
    now = datetime(2026, 8, 8, 3, tzinfo=UTC)
    project = _project("project-1", "经营分析", instructions="使用统一经营口径")
    response = _response(
        "response-1",
        "conversation-1",
        "incomplete",
        now,
        error_message="达到可恢复执行上限",
    )

    result = build_workbench_portfolio(
        projects=[project],
        sessions=[
            SimpleNamespace(
                id="conversation-1", project_id="project-1", display_title="月报生成", title=""
            )
        ],
        responses=[response],
        goals=[],
        pending_approvals=[],
        tasks=[],
        alerts=[],
        alert_events=[],
        now=now,
        response_candidate_limit=500,
        response_candidates_truncated=True,
    )

    item = result["items"][0]
    assert item["status"] == "critical"
    assert item["next_action"]["label"] == "检查并重试"
    assert item["next_action"]["route"] == "/chat?conversation=conversation-1"
    assert item["next_action"]["description"] == "达到可恢复执行上限"
    assert result["response_candidate_limit"] == 500
    assert result["response_candidates_truncated"] is True


def test_portfolio_keeps_approval_project_when_response_candidates_are_truncated() -> None:
    now = datetime(2026, 8, 8, 3, tzinfo=UTC)
    project = _project("project-1", "经营分析", instructions="使用统一经营口径")
    approval = SimpleNamespace(
        response_id="response-outside-candidates",
        tool_name="create_data_alert",
        side_effect_level="write",
        created_at=now,
    )

    result = build_workbench_portfolio(
        projects=[project],
        sessions=[],
        responses=[],
        goals=[],
        pending_approvals=[(approval, "conversation-older", "project-1")],
        tasks=[],
        alerts=[],
        alert_events=[],
        now=now,
    )

    assert len(result["items"]) == 1
    assert result["items"][0]["project_id"] == "project-1"
    assert result["items"][0]["pending_approvals"] == 1
    assert result["items"][0]["next_action"]["route"] == ("/chat?conversation=conversation-older")


def test_portfolio_remains_a_bounded_read_only_projection() -> None:
    portfolio_source = (ROOT / "services/workbench_portfolio.py").read_text(encoding="utf-8")
    overview_source = (ROOT / "services/enterprise_workbench.py").read_text(encoding="utf-8")

    assert "sqlalchemy" not in portfolio_source
    assert "db.add" not in portfolio_source
    assert "db.commit" not in portfolio_source
    assert "create_response" not in portfolio_source
    assert "WORKBENCH_RESPONSE_CANDIDATE_LIMIT = 500" in overview_source
    assert "response_candidates_truncated" in overview_source
    assert '"portfolio": portfolio' in overview_source
