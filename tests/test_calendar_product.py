"""个人日历、Agent 工具与时间型记忆主链路合约。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.api_gateway.main import app
from gateway.api_gateway.routers.agent_resources import (
    ScheduledTaskPayload,
    SchedulePreviewPayload,
    _owned_notification_subjects,
)
from gateway.api_gateway.routers.alerts import AlertRulePayload
from gateway.api_gateway.routers.responses import OpenTraceOptions
from infra.config.constants import DEFAULT_TIMEZONE
from services.calendar import (
    CalendarValidationError,
    _expanded_occurrences,
    calendar_event_lifecycle,
    cancel_calendar_event_record,
    create_calendar_event_record,
    normalize_recurrence_rule,
    parse_calendar_datetime,
    update_calendar_event_record,
)

ROOT = Path(__file__).resolve().parents[1]


def test_calendar_api_is_exposed_on_v2_with_crud_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v2/calendar/events" in paths
    assert {"get", "post"}.issubset(paths["/api/v2/calendar/events"])
    assert "/api/v2/calendar/events/{event_id}" in paths
    assert {"get", "patch", "delete"}.issubset(paths["/api/v2/calendar/events/{event_id}"])
    assert "/api/v2/calendar/events/{event_id}/history" in paths
    assert paths["/api/v2/calendar/events"]["get"]["tags"] == ["calendar"]
    parameters = paths["/api/v2/calendar/events"]["get"]["parameters"]
    assert "include_cancelled" in {parameter["name"] for parameter in parameters}


def test_relative_date_target_can_be_normalized_in_user_timezone() -> None:
    # 当前日期是 2026-07-29；用户说“明天 09:00”时应落到 2026-07-30。
    result = parse_calendar_datetime(datetime(2026, 7, 30, 9, 0), "Asia/Shanghai")
    assert result == datetime(2026, 7, 30, 1, 0, tzinfo=UTC)


def test_user_facing_time_defaults_are_beijing_time() -> None:
    assert DEFAULT_TIMEZONE == "Asia/Shanghai"
    assert OpenTraceOptions().timezone == DEFAULT_TIMEZONE
    assert SchedulePreviewPayload(expression="每天 09:00").timezone == DEFAULT_TIMEZONE
    assert (
        ScheduledTaskPayload(
            title="日报",
            prompt="生成每日数据日报",
            rrule="FREQ=DAILY",
        ).timezone
        == DEFAULT_TIMEZONE
    )
    assert (
        AlertRulePayload(
            name="余额预警",
            question="查询当前账户余额",
            data_source_id="source-1",
            threshold=100,
            rrule="FREQ=DAILY",
        ).timezone
        == DEFAULT_TIMEZONE
    )


def test_recurring_calendar_event_expands_into_instances() -> None:
    row = SimpleNamespace(
        id="event-1",
        start_at=datetime(2026, 7, 29, 1, 0, tzinfo=UTC),
        end_at=datetime(2026, 7, 29, 2, 0, tzinfo=UTC),
        recurrence_rule=normalize_recurrence_rule("FREQ=DAILY;COUNT=3"),
    )
    instances = _expanded_occurrences(
        row,
        start_at=datetime(2026, 7, 29, 0, 0, tzinfo=UTC),
        end_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
    )
    assert [item[0] for item in instances] == [
        datetime(2026, 7, 29, 1, 0, tzinfo=UTC),
        datetime(2026, 7, 30, 1, 0, tzinfo=UTC),
        datetime(2026, 7, 31, 1, 0, tzinfo=UTC),
    ]
    assert all(item[2] and item[2].startswith("event-1:") for item in instances)


def test_calendar_recurrence_rejects_high_frequency_rules() -> None:
    with pytest.raises(CalendarValidationError, match="unsupported_recurrence_frequency"):
        normalize_recurrence_rule("FREQ=MINUTELY")


def test_calendar_queries_keep_user_tenant_workspace_boundaries() -> None:
    source = (ROOT / "services/calendar.py").read_text(encoding="utf-8")
    assert "CalendarEvent.user_id == user_id" in source
    assert "CalendarEvent.tenant_id == tenant_id" in source
    assert "CalendarEvent.workspace_id == workspace_id" in source
    router = (ROOT / "gateway/api_gateway/routers/calendar.py").read_text(encoding="utf-8")
    assert "get_scoped_calendar_event(" in router
    assert "user_id=current_user.id" in router
    assert "tenant_id=tenant_id" in router
    assert "workspace_id=workspace_id" in router


def test_calendar_is_injected_as_first_class_memory_context() -> None:
    source = (ROOT / "kernel/agent_loop/context.py").read_text(encoding="utf-8")
    assert "upcoming_calendar_context" in source
    assert "个人日历（一级记忆来源）" in source
    assert '"calendar_event_count"' in source
    assert '"calendar_timezone"' in source


def test_calendar_tools_are_typed_and_writes_require_approval() -> None:
    from tools.builtin_tools import platform_tools as _platform_tools  # noqa: F401
    from tools.registry.registry import registry

    list_tool = registry.get("list_calendar_events")
    create_tool = registry.get("create_calendar_event")
    update_tool = registry.get("update_calendar_event")
    cancel_tool = registry.get("cancel_calendar_event")
    history_tool = registry.get("get_calendar_event_history")
    assert list_tool is not None and list_tool.side_effect == "read"
    assert create_tool is not None and create_tool.side_effect == "write"
    assert update_tool is not None and update_tool.side_effect == "write"
    assert cancel_tool is not None and cancel_tool.side_effect == "destructive"
    assert history_tool is not None and history_tool.side_effect == "read"
    assert create_tool.max_retries == 0
    assert cancel_tool.max_retries == 0
    matches = registry.match("明天下午三点客户复盘，帮我记录到日历", top_k=5)
    assert "create_calendar_event" in {item.name for item in matches}


def test_calendar_tool_defensively_normalizes_model_string_values() -> None:
    from tools.builtin_tools.platform_tools import _as_bool, _as_int_list

    assert _as_bool("False") is False
    assert _as_bool("true") is True
    assert _as_int_list("[10, 30]", default=[15]) == [10, 30]


def test_calendar_tool_scope_is_hydrated_by_agent_loop() -> None:
    source = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")
    for name in (
        "list_calendar_events",
        "get_calendar_event_history",
        "create_calendar_event",
        "update_calendar_event",
        "cancel_calendar_event",
    ):
        assert f'"{name}"' in source
    assert '"response_id": response.id' in source
    assert 'extension.get("timezone")' in source


def test_calendar_migration_and_runtime_readiness_are_registered() -> None:
    migration = (ROOT / "alembic/versions/r0006_calendar_events.py").read_text(encoding="utf-8")
    runtime = (ROOT / "infra/storage/database.py").read_text(encoding="utf-8")
    assert 'revision = "r0006_calendar_events"' in migration
    assert 'down_revision = "r0005_user_model_settings"' in migration
    assert "CREATE TABLE IF NOT EXISTS public.calendar_events" in migration
    assert "CREATE TABLE IF NOT EXISTS public.calendar_reminder_deliveries" in migration
    assert '"calendar_events"' in runtime
    assert '"calendar_reminder_deliveries"' in runtime
    lifecycle_migration = (ROOT / "alembic/versions/r0013_calendar_memory_lifecycle.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "r0013_calendar_memory_lifecycle"' in lifecycle_migration
    assert 'down_revision = "r0012_company_brain"' in lifecycle_migration
    assert "calendar_event_revisions" in lifecycle_migration
    assert '"calendar_event_revisions"' in runtime
    timezone_defaults = (ROOT / "alembic/versions/r0010_beijing_timezone_defaults.py").read_text(
        encoding="utf-8"
    )
    assert "ALTER COLUMN timezone SET DEFAULT 'Asia/Shanghai'" in timezone_defaults


def test_calendar_reminders_join_worker_and_notification_center() -> None:
    scheduler = (ROOT / "infra/calendar/scheduler.py").read_text(encoding="utf-8")
    worker = (ROOT / "agents/worker.py").read_text(encoding="utf-8")
    notifications = (ROOT / "gateway/api_gateway/routers/agent_resources.py").read_text(
        encoding="utf-8"
    )
    assert "CalendarReminderDelivery" in scheduler
    assert "TaskNotification" in scheduler
    assert "calendar_reminder_loop" in worker
    assert "select(CalendarEvent.id)" in notifications
    assert '"calendar"' in notifications


def test_notification_ownership_query_builds_three_way_union() -> None:
    statement = _owned_notification_subjects(
        user_id="user-a",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
    )

    assert str(statement).upper().count(" UNION ") == 2


def _calendar_row(**overrides):
    values = {
        "id": "event-1",
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "title": "客户评审",
        "description": "",
        "location": "",
        "event_type": "meeting",
        "start_at": datetime(2026, 8, 3, 1, 0, tzinfo=UTC),
        "end_at": datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        "timezone": "Asia/Shanghai",
        "all_day": False,
        "recurrence_rule": None,
        "reminder_minutes": [15],
        "status": "confirmed",
        "source": "assistant",
        "source_response_id": "response-1",
        "revision": 1,
        "cancelled_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_calendar_lifecycle_keeps_history_out_of_current_commitments() -> None:
    row = _calendar_row()
    assert calendar_event_lifecycle(row, now=datetime(2026, 8, 3, 0, 0, tzinfo=UTC)) == "upcoming"
    assert (
        calendar_event_lifecycle(row, now=datetime(2026, 8, 3, 1, 30, tzinfo=UTC)) == "in_progress"
    )
    assert calendar_event_lifecycle(row, now=datetime(2026, 8, 3, 3, 0, tzinfo=UTC)) == "completed"
    row.status = "cancelled"
    assert calendar_event_lifecycle(row, now=datetime(2026, 8, 3, 0, 0, tzinfo=UTC)) == "cancelled"
    row.status = "confirmed"
    row.recurrence_rule = "RRULE:FREQ=WEEKLY"
    assert calendar_event_lifecycle(row, now=datetime(2026, 8, 3, 3, 0, tzinfo=UTC)) == "recurring"


@pytest.mark.asyncio
async def test_calendar_create_flushes_parent_before_revision() -> None:
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())

    row = await create_calendar_event_record(
        db,
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        title="客户评审",
        start_at="2026-08-03T09:00:00+08:00",
        end_at="2026-08-03T10:00:00+08:00",
        timezone_name="Asia/Shanghai",
        reminder_minutes=[30, 15, 15],
        source="assistant",
        source_response_id="response-1",
    )

    assert row.revision == 1
    assert row.reminder_minutes == [15, 30]
    db.flush.assert_awaited_once()
    assert db.add.call_count == 2
    revision = db.add.call_args.args[0]
    assert revision.event_id == row.id
    assert revision.action == "created"


@pytest.mark.asyncio
async def test_reschedule_preserves_duration_and_appends_revision() -> None:
    row = _calendar_row()
    db = SimpleNamespace(add=Mock())

    await update_calendar_event_record(
        db,
        row=row,
        changes={"start_at": "2026-08-04T09:00:00+08:00"},
        source="assistant",
        source_response_id="response-2",
    )

    assert row.start_at == datetime(2026, 8, 4, 1, 0, tzinfo=UTC)
    assert row.end_at - row.start_at == timedelta(hours=1)
    assert row.revision == 2
    revision = db.add.call_args.args[0]
    assert revision.action == "updated"
    assert revision.revision == 2
    assert revision.changed_fields == ["end_at", "start_at"]
    assert revision.source_response_id == "response-2"


@pytest.mark.asyncio
async def test_cancel_is_audited_idempotently_and_cannot_be_resurrected() -> None:
    row = _calendar_row()
    db = SimpleNamespace(add=Mock())
    cancelled_at = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)

    await cancel_calendar_event_record(
        db,
        row=row,
        source="manual",
        now=cancelled_at,
    )
    await cancel_calendar_event_record(db, row=row, source="manual", now=cancelled_at)

    assert row.status == "cancelled"
    assert row.cancelled_at == cancelled_at
    assert row.revision == 2
    assert db.add.call_count == 1
    with pytest.raises(CalendarValidationError, match="calendar_event_cancelled"):
        await update_calendar_event_record(
            db,
            row=row,
            changes={"title": "不应复活"},
            source="manual",
        )
