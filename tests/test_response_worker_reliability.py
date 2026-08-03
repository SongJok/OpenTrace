from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from infra.responses import worker


class _SessionContext:
    def __init__(self, session: AsyncMock) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *_args) -> None:
        return None


def test_response_id_from_stream_fields_accepts_bytes() -> None:
    response_id = worker._response_id_from_stream_fields(
        {"data": json.dumps({"response_id": "resp-1"}).encode("utf-8")}
    )

    assert response_id == "resp-1"


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"data": "not-json"},
        {"data": "[]"},
        {"data": json.dumps({"response_id": ""})},
    ],
)
def test_response_id_from_stream_fields_rejects_poison_messages(fields: dict) -> None:
    with pytest.raises((json.JSONDecodeError, ValueError)):
        worker._response_id_from_stream_fields(fields)


@pytest.mark.asyncio
async def test_invalid_stream_message_is_acked_without_claiming_arbitrary_response(
    monkeypatch,
) -> None:
    redis = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(worker, "execute_response", execute)

    processed = await worker._process_stream_message(
        redis,
        "message-1",
        {"data": json.dumps({"outbox_id": "outbox-1"})},
        asyncio.Semaphore(1),
    )

    assert processed is False
    execute.assert_not_awaited()
    redis.xack.assert_awaited_once_with(worker.STREAM, worker.GROUP, "message-1")


@pytest.mark.asyncio
async def test_cancel_while_waiting_for_tenant_slot_stops_lease_heartbeat(monkeypatch) -> None:
    db = AsyncMock()
    response = SimpleNamespace(
        id="resp-cancelled-wait",
        tenant_id="tenant-1",
        created_at=None,
        attempt_count=1,
    )
    heartbeat_started = asyncio.Event()
    heartbeat_stopped = asyncio.Event()
    tenant_limit = asyncio.Semaphore(0)

    async def heartbeat(_response_id: str) -> None:
        heartbeat_started.set()
        try:
            await asyncio.Future()
        finally:
            heartbeat_stopped.set()

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: _SessionContext(db))
    monkeypatch.setattr(worker, "set_worker_session", AsyncMock())
    monkeypatch.setattr(worker, "claim_response", AsyncMock(return_value=response))
    monkeypatch.setattr(worker, "append_event", AsyncMock())
    monkeypatch.setattr(worker, "_heartbeat", heartbeat)
    monkeypatch.setattr(worker, "_tenant_semaphore", lambda _tenant_id: tenant_limit)

    task = asyncio.create_task(worker.execute_response(response.id))
    await asyncio.wait_for(heartbeat_started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.wait_for(heartbeat_stopped.wait(), timeout=1)
    assert tenant_limit._value == 0


@pytest.mark.asyncio
async def test_expired_final_attempt_is_converged_to_failed(monkeypatch) -> None:
    db = AsyncMock()
    response = SimpleNamespace(
        id="resp-exhausted",
        status="in_progress",
        error_code=None,
        error_message=None,
        completed_at=None,
        goal_id=None,
        attempt_count=3,
        max_attempts=3,
        lease_owner="dead-worker",
        lease_expires_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
    )
    append_event = AsyncMock()
    update_task_run = AsyncMock()
    release_lease = AsyncMock()

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: _SessionContext(db))
    monkeypatch.setattr(worker, "set_worker_session", AsyncMock())
    monkeypatch.setattr(worker, "claim_response", AsyncMock(return_value=None))
    monkeypatch.setattr(
        worker,
        "claim_exhausted_response",
        AsyncMock(return_value=response),
    )
    monkeypatch.setattr(worker, "append_event", append_event)
    monkeypatch.setattr(worker, "_update_task_run", update_task_run)
    monkeypatch.setattr(worker, "release_lease", release_lease)

    processed = await worker.execute_response(response.id)

    assert processed is True
    assert response.status == "failed"
    assert response.error_code == "response_attempts_exhausted"
    assert response.completed_at is not None
    append_event.assert_awaited_once()
    update_task_run.assert_awaited_once_with(
        db,
        response,
        status="failed",
        error=response.error_message,
        finished=True,
    )
    release_lease.assert_awaited_once_with(db, response)
    db.commit.assert_awaited_once()
