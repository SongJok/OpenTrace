from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from gateway.api_gateway.routers.agent_resources import (
    SchedulePreviewPayload,
    _validate_project_bindings,
    preview_scheduled_task,
    run_scheduled_task,
    scheduled_task_action,
)
from infra.errors import AppException
from infra.storage.models import User


@pytest.mark.asyncio
async def test_project_rejects_inaccessible_data_source_binding() -> None:
    db = AsyncMock()
    with patch(
        "gateway.api_gateway.routers.agent_resources.get_accessible_data_source",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(AppException):
            await _validate_project_bindings(
                db,
                user_id="user-1",
                tenant_id="tenant-1",
                workspace_id="workspace-1",
                assistant_profile_id=None,
                data_source_ids=["source-other"],
            )


@pytest.mark.asyncio
async def test_enable_scheduled_task_calculates_next_run() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    user = User(id="user-1", email="test@example.com")
    row = SimpleNamespace(
        id="task-1",
        title="每日检查",
        description="检查系统状态",
        rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
        timezone="Asia/Shanghai",
        status="draft",
        project_id=None,
        conversation_id=None,
        requires_confirmation=True,
        last_run_at=None,
        next_run_at=None,
    )
    db = AsyncMock()
    db.scalar.return_value = row

    result = await scheduled_task_action("task-1", "enable", request, user, db)

    assert result["status"] == "active"
    assert result["next_run_at"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_preview_scheduled_task_returns_five_bounded_runs() -> None:
    starts_at = datetime.now(UTC) + timedelta(days=1)
    ends_at = starts_at + timedelta(days=10)
    result = await preview_scheduled_task(
        SchedulePreviewPayload(
            rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
            timezone="Asia/Shanghai",
            starts_at=starts_at,
            ends_at=ends_at,
            count=5,
        ),
        User(id="user-1", email="test@example.com"),
    )

    assert len(result["next_run_times"]) == 5
    assert result["next_run_at"] == result["next_run_times"][0]
    assert result["starts_at"] == starts_at.isoformat()


@pytest.mark.asyncio
async def test_manual_run_queues_response_without_changing_schedule() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    user = User(id="user-1", email="test@example.com")
    next_run_at = SimpleNamespace(isoformat=lambda: "2026-07-21T01:00:00+00:00")
    row = SimpleNamespace(
        id="task-1",
        user_id="user-1",
        tenant_id="default",
        workspace_id="default",
        status="paused",
        next_run_at=next_run_at,
    )
    run = SimpleNamespace(
        id="run-1",
        task_id="task-1",
        status="queued",
        response_id="resp-1",
        scheduled_for=datetime.now(UTC),
    )
    db = AsyncMock()
    db.scalar.return_value = row

    with patch(
        "infra.responses.scheduler.queue_task_run",
        new=AsyncMock(return_value=run),
    ) as queue:
        result = await run_scheduled_task("task-1", request, user, db)

    assert result["status"] == "queued"
    assert row.status == "paused"
    assert row.next_run_at is next_run_at
    assert queue.await_args.kwargs["trigger"] == "manual"
    db.commit.assert_awaited_once()
