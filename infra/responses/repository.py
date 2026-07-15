from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import ResponseEvent, ResponseOutbox, ResponseRecord

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "incomplete"}


async def append_event(
    db: AsyncSession,
    *,
    response_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> ResponseEvent:
    # Serialise sequence allocation with all API/worker writers.
    await db.scalar(select(ResponseRecord.id).where(ResponseRecord.id == response_id).with_for_update())
    current = await db.scalar(
        select(func.max(ResponseEvent.sequence_number)).where(ResponseEvent.response_id == response_id)
    )
    event = ResponseEvent(
        id=f"evt_{uuid.uuid4().hex}",
        response_id=response_id,
        sequence_number=int(current if current is not None else -1) + 1,
        event_type=event_type,
        payload=payload,
    )
    db.add(event)
    await db.flush()
    return event


def add_outbox(
    db: AsyncSession,
    *,
    response_id: str,
    event_type: str = "response.execute",
    suffix: str = "create",
) -> ResponseOutbox:
    row = ResponseOutbox(
        id=f"outbox_{uuid.uuid4().hex}",
        event_key=f"{event_type}:{response_id}:{suffix}",
        aggregate_id=response_id,
        aggregate_type="response",
        event_type=event_type,
        payload={"response_id": response_id},
    )
    db.add(row)
    return row


async def claim_response(
    db: AsyncSession,
    *,
    owner: str,
    response_id: str | None = None,
    lease_seconds: int = 120,
) -> ResponseRecord | None:
    now = datetime.now(UTC)
    query = (
        select(ResponseRecord)
        .where(
            ResponseRecord.status.in_(["queued", "in_progress"]),
            or_(ResponseRecord.lease_expires_at.is_(None), ResponseRecord.lease_expires_at < now),
            ResponseRecord.attempt_count < ResponseRecord.max_attempts,
        )
        .order_by(ResponseRecord.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if response_id:
        query = query.where(ResponseRecord.id == response_id)
    row = await db.scalar(query)
    if row is None:
        return None
    row.lease_owner = owner
    row.lease_expires_at = now + timedelta(seconds=max(15, lease_seconds))
    row.heartbeat_at = now
    row.attempt_count = int(row.attempt_count or 0) + 1
    if row.status == "queued":
        row.status = "in_progress"
    await db.flush()
    return row


async def renew_lease(db: AsyncSession, response_id: str, owner: str, lease_seconds: int = 120) -> bool:
    row = await db.scalar(
        select(ResponseRecord).where(
            ResponseRecord.id == response_id,
            ResponseRecord.lease_owner == owner,
            ResponseRecord.status == "in_progress",
        )
    )
    if row is None:
        return False
    now = datetime.now(UTC)
    row.heartbeat_at = now
    row.lease_expires_at = now + timedelta(seconds=max(15, lease_seconds))
    await db.commit()
    return True


async def release_lease(db: AsyncSession, response: ResponseRecord) -> None:
    response.lease_owner = None
    response.lease_expires_at = None
    response.heartbeat_at = None
    await db.flush()
