from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from infra.responses.worker import _update_task_run


@pytest.mark.asyncio
async def test_incomplete_task_run_is_not_reported_as_success() -> None:
    run = SimpleNamespace(
        id="run-1",
        task_id="task-1",
        user_id="user-1",
        status="queued",
        output=None,
        error=None,
        finished_at=None,
    )
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[run, "日报生成", None])
    response = SimpleNamespace(id="resp-1")

    await _update_task_run(
        db,
        response,
        status="incomplete",
        output="部分结果",
        finished=True,
    )

    assert run.status == "incomplete"
    assert run.finished_at is not None
    notification = db.add.call_args.args[0]
    assert notification.level == "warning"
    assert notification.title == "日报生成未完整完成"


@pytest.mark.asyncio
async def test_task_waiting_for_approval_remains_resumable() -> None:
    run = SimpleNamespace(
        id="run-2",
        task_id="task-2",
        user_id="user-1",
        status="queued",
        output=None,
        error=None,
        finished_at=None,
    )
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[run, "发布报告", None])

    await _update_task_run(
        db,
        SimpleNamespace(id="resp-2"),
        status="requires_action",
        output="需要批准发送邮件",
    )

    assert run.status == "requires_action"
    assert run.finished_at is None
    assert db.add.call_args.args[0].title == "发布报告等待确认"
