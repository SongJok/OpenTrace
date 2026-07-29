"""持久化个人日历提醒调度。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from infra.observability.logger import get_logger
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    CalendarEvent,
    CalendarReminderDelivery,
    TaskNotification,
)
from services.calendar import _expanded_occurrences

logger = get_logger(__name__)
MAX_REMINDER_MINUTES = 10_080


async def deliver_due_calendar_reminders(now: datetime | None = None) -> int:
    """生成到期提醒；账本保证同一事件实例和提醒偏移只投递一次。"""

    now = (now or datetime.now(UTC)).astimezone(UTC)
    horizon = now + timedelta(minutes=MAX_REMINDER_MINUTES + 1)
    grace_start = now - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        events = list(
            (
                await db.execute(
                    select(CalendarEvent).where(
                        CalendarEvent.status == "confirmed",
                        CalendarEvent.start_at < horizon,
                        or_(
                            CalendarEvent.recurrence_rule.is_not(None),
                            CalendarEvent.end_at > grace_start,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        delivered = 0
        for event in events:
            reminders = sorted(
                {
                    int(value)
                    for value in (event.reminder_minutes or [])
                    if 0 <= int(value) <= MAX_REMINDER_MINUTES
                }
            )
            if not reminders:
                continue
            for occurrence_start, _occurrence_end, _occurrence_id in _expanded_occurrences(
                event,
                start_at=grace_start,
                end_at=horizon,
            ):
                if occurrence_start < grace_start:
                    continue
                for reminder_minutes in reminders:
                    due_at = occurrence_start - timedelta(minutes=reminder_minutes)
                    if due_at > now:
                        continue
                    delivery_id = str(uuid.uuid4())
                    inserted = await db.scalar(
                        insert(CalendarReminderDelivery)
                        .values(
                            id=delivery_id,
                            event_id=event.id,
                            occurrence_start=occurrence_start,
                            reminder_minutes=reminder_minutes,
                            delivered_at=now,
                        )
                        .on_conflict_do_nothing(constraint="uq_calendar_reminder_delivery")
                        .returning(CalendarReminderDelivery.id)
                    )
                    if inserted is None:
                        continue
                    local_start = occurrence_start.astimezone(ZoneInfo(event.timezone))
                    body = (
                        f"{local_start.strftime('%Y-%m-%d %H:%M')} · {event.location}"
                        if event.location
                        else local_start.strftime("%Y-%m-%d %H:%M")
                    )
                    db.add(
                        TaskNotification(
                            id=str(uuid.uuid4()),
                            user_id=event.user_id,
                            task_id=event.id,
                            run_id=delivery_id,
                            level="info",
                            title=f"日程提醒：{event.title}",
                            body=body,
                            read=False,
                        )
                    )
                    delivered += 1
        if delivered:
            await db.commit()
        return delivered


async def calendar_reminder_loop() -> None:
    while True:
        try:
            await deliver_due_calendar_reminders()
        except Exception as exc:  # noqa: BLE001
            logger.warning("calendar_reminder_delivery_failed", error=str(exc))
        await asyncio.sleep(30)
