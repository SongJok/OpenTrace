from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from gateway.api_gateway.routers.agent_resources import (
    _validate_project_bindings,
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
