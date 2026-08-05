"""企业工作台今日脉搏的优先级与时序投影合约。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from gateway.api_gateway.main import app
from services.workbench_pulse import (
    build_workbench_operating_pulse,
    rank_workbench_actions,
)


def test_workbench_api_accepts_an_explicit_view_timezone() -> None:
    operation = app.openapi()["paths"]["/api/v2/workbench/overview"]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert parameters["timezone"]["schema"]["default"] == "Asia/Shanghai"


def test_action_priority_is_deterministic_and_explainable() -> None:
    now = datetime(2026, 8, 5, 2, tzinfo=UTC)
    ranked = rank_workbench_actions(
        [
            {
                "id": "approval-1",
                "type": "approval",
                "severity": "warning",
                "title": "待审批",
                "description": "等待确认",
                "route": "/chat",
                "created_at": (now - timedelta(hours=5)).isoformat(),
            },
            {
                "id": "alert-1",
                "type": "alert",
                "severity": "critical",
                "title": "关键指标异常",
                "description": "等待确认",
                "route": "/alerts",
                "created_at": (now - timedelta(minutes=5)).isoformat(),
            },
        ],
        now=now,
    )

    assert [item["id"] for item in ranked] == ["alert-1", "approval-1"]
    assert ranked[0]["priority"] == "p0"
    assert ranked[1]["priority"] == "p1"
    assert ranked[1]["age_minutes"] == 300
    assert "审批已等待" in ranked[1]["priority_reason"]


def test_operating_pulse_combines_today_calendar_automation_and_stale_goals() -> None:
    now = datetime(2026, 8, 5, 2, tzinfo=UTC)  # Asia/Shanghai 10:00
    pulse = build_workbench_operating_pulse(
        attention_items=[
            {
                "id": "response-1",
                "type": "response",
                "severity": "error",
                "title": "AI 工作执行未完成",
                "description": "可安全重试",
                "route": "/chat",
                "created_at": (now - timedelta(minutes=20)).isoformat(),
            },
            {
                "id": "notification-duplicate",
                "type": "notification",
                "severity": "warning",
                "title": "经营日报执行异常",
                "description": "任务通知",
                "route": "/reports",
                "resource_id": "task-overdue",
                "created_at": (now - timedelta(hours=2)).isoformat(),
            },
        ],
        tasks=[
            SimpleNamespace(
                id="task-overdue",
                title="经营日报",
                task_type="enterprise_report",
                status="active",
                next_run_at=now - timedelta(hours=3),
            ),
            SimpleNamespace(
                id="task-future",
                title="下午简报",
                task_type="agent_task",
                status="active",
                next_run_at=now + timedelta(hours=4),
            ),
        ],
        alerts=[
            SimpleNamespace(
                id="alert-rule-1",
                name="现金流监控",
                status="active",
                next_run_at=now + timedelta(hours=1),
            )
        ],
        goals=[
            SimpleNamespace(
                id="goal-1",
                objective="完成企业经营月报自动化",
                status="in_progress",
                updated_at=now - timedelta(days=4),
            )
        ],
        calendar_events=[
            {
                "id": "meeting-1",
                "title": "经营复盘会",
                "location": "会议室 A",
                "event_type": "meeting",
                "start_at": (now + timedelta(hours=1)).isoformat(),
                "end_at": (now + timedelta(hours=1, minutes=45)).isoformat(),
            },
            {
                "id": "focus-1",
                "title": "月报深度工作",
                "event_type": "focus",
                "start_at": (now + timedelta(hours=3)).isoformat(),
                "end_at": (now + timedelta(hours=4)).isoformat(),
            },
        ],
        timezone_name="Asia/Shanghai",
        now=now,
    )

    assert pulse["local_date"] == "2026-08-05"
    assert pulse["status"] == "critical"
    assert pulse["summary"] == {
        "urgent_items": 3,
        "calendar_events": 2,
        "due_automations": 3,
        "overdue_automations": 1,
        "stale_goals": 1,
        "focus_minutes": 60,
        "meeting_minutes": 45,
    }
    assert pulse["focus_items"][0]["id"] == "task-overdue"
    assert pulse["focus_items"][0]["priority"] == "p0"
    assert {item["id"] for item in pulse["timeline"]} == {
        "task-overdue",
        "task-future",
        "alert-rule-1",
        "meeting-1",
        "focus-1",
    }
    assert any(item["id"] == "goal-1" for item in pulse["focus_items"])
    assert all(item["id"] != "notification-duplicate" for item in pulse["focus_items"])


def test_operating_pulse_respects_the_local_day_boundary() -> None:
    now = datetime(2026, 8, 5, 1, tzinfo=UTC)  # Asia/Shanghai 09:00
    pulse = build_workbench_operating_pulse(
        attention_items=[],
        tasks=[],
        alerts=[],
        goals=[],
        calendar_events=[
            {
                "id": "previous-day",
                "title": "前一天安排",
                "event_type": "event",
                "start_at": datetime(2026, 8, 4, 15, tzinfo=UTC).isoformat(),
                "end_at": datetime(2026, 8, 4, 15, 30, tzinfo=UTC).isoformat(),
            },
            {
                "id": "today",
                "title": "今日安排",
                "event_type": "event",
                "start_at": datetime(2026, 8, 4, 16, 30, tzinfo=UTC).isoformat(),
                "end_at": datetime(2026, 8, 4, 17, tzinfo=UTC).isoformat(),
            },
            {
                "id": "spanning-focus",
                "title": "跨日专注",
                "event_type": "focus",
                "start_at": datetime(2026, 8, 4, 15, 30, tzinfo=UTC).isoformat(),
                "end_at": datetime(2026, 8, 4, 16, 30, tzinfo=UTC).isoformat(),
            },
        ],
        timezone_name="Asia/Shanghai",
        now=now,
    )

    assert [item["id"] for item in pulse["timeline"]] == ["spanning-focus", "today"]
    assert pulse["summary"]["focus_minutes"] == 30
    assert pulse["day_start"] == "2026-08-04T16:00:00+00:00"
    assert pulse["day_end"] == "2026-08-05T16:00:00+00:00"
