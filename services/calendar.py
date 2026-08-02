"""个人日历领域服务。

日历是用户的一级记忆资源，而不是定时任务的别名：事件记录事实时间、时区和重复规则，
查询时再按用户视图展开实例。所有调用方必须先完成 user、tenant、workspace 作用域过滤。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.constants import DEFAULT_TIMEZONE
from infra.storage.models import CalendarEvent, CalendarEventRevision, User

DEFAULT_CALENDAR_TIMEZONE = DEFAULT_TIMEZONE
MAX_EXPANDED_EVENTS = 200


class CalendarValidationError(ValueError):
    """用户日历输入不合法。"""


def ensure_timezone(value: str | None) -> str:
    timezone_name = (value or DEFAULT_CALENDAR_TIMEZONE).strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise CalendarValidationError(f"invalid_timezone:{timezone_name}") from exc
    return timezone_name


def parse_calendar_datetime(value: datetime | str, timezone_name: str) -> datetime:
    """将 ISO 时间解释为用户时区，并统一存储为 UTC。"""
    timezone_name = ensure_timezone(timezone_name)
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(UTC)


def local_day_window(day: date, timezone_name: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(ensure_timezone(timezone_name))
    start = datetime.combine(day, time.min, tzinfo=zone)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def default_calendar_window(timezone_name: str, *, days: int = 31) -> tuple[datetime, datetime]:
    zone = ZoneInfo(ensure_timezone(timezone_name))
    now = datetime.now(zone)
    start = datetime.combine(now.date(), time.min, tzinfo=zone)
    return start.astimezone(UTC), (start + timedelta(days=days)).astimezone(UTC)


def normalize_recurrence_rule(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    rule = value.strip()
    if not rule.upper().startswith("RRULE:"):
        rule = f"RRULE:{rule}"
    upper_rule = rule.upper()
    if not any(
        marker in upper_rule
        for marker in ("FREQ=DAILY", "FREQ=WEEKLY", "FREQ=MONTHLY", "FREQ=YEARLY")
    ):
        raise CalendarValidationError("unsupported_recurrence_frequency")
    try:
        rrulestr(rule)
    except (TypeError, ValueError) as exc:
        raise CalendarValidationError("invalid_recurrence_rule") from exc
    return rule


def validate_event_window(
    start_at: datetime,
    end_at: datetime,
    *,
    all_day: bool,
    timezone_name: str = DEFAULT_CALENDAR_TIMEZONE,
) -> None:
    if end_at <= start_at:
        raise CalendarValidationError("event_end_must_be_after_start")
    if all_day:
        zone = ZoneInfo(ensure_timezone(timezone_name))
        if (
            start_at.astimezone(zone).time() != time.min
            or end_at.astimezone(zone).time() != time.min
        ):
            raise CalendarValidationError("all_day_event_must_use_midnight_boundary")
    if end_at - start_at > timedelta(days=366):
        raise CalendarValidationError("event_duration_too_long")


def normalize_reminder_minutes(values: list[int] | None) -> list[int]:
    normalized = sorted({int(value) for value in (values or []) if 0 <= int(value) <= 10080})
    if len(normalized) > 5:
        raise CalendarValidationError("too_many_calendar_reminders")
    return normalized


def calendar_event_lifecycle(
    row: CalendarEvent,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    occurrence_id: str | None = None,
    now: datetime | None = None,
) -> str:
    """计算事件的时间状态，不用后台任务篡改历史事实。"""

    if row.status == "cancelled":
        return "cancelled"
    if row.recurrence_rule and occurrence_id is None:
        return "recurring"
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    start = start_at or row.start_at
    end = end_at or row.end_at
    if current < start:
        return "upcoming"
    if current < end:
        return "in_progress"
    return "completed"


def event_to_dict(
    row: CalendarEvent,
    *,
    timezone_name: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    occurrence_id: str | None = None,
) -> dict[str, Any]:
    zone = ZoneInfo(ensure_timezone(timezone_name))
    start_utc = start_at or row.start_at
    end_utc = end_at or row.end_at
    return {
        "id": row.id,
        "occurrence_id": occurrence_id or row.id,
        "title": row.title,
        "description": row.description or "",
        "location": row.location or "",
        "event_type": row.event_type,
        "start_at": start_utc.astimezone(UTC).isoformat(),
        "end_at": end_utc.astimezone(UTC).isoformat(),
        "local_start_at": start_utc.astimezone(zone).isoformat(),
        "local_end_at": end_utc.astimezone(zone).isoformat(),
        "timezone": row.timezone,
        "view_timezone": timezone_name,
        "all_day": bool(row.all_day),
        "recurrence_rule": row.recurrence_rule,
        "reminder_minutes": list(row.reminder_minutes or []),
        "status": row.status,
        "lifecycle_status": calendar_event_lifecycle(
            row,
            start_at=start_utc,
            end_at=end_utc,
            occurrence_id=occurrence_id,
        ),
        "source": row.source,
        "source_response_id": row.source_response_id,
        "revision": int(row.revision or 1),
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _calendar_snapshot(row: CalendarEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description or "",
        "location": row.location or "",
        "event_type": row.event_type,
        "start_at": row.start_at.astimezone(UTC).isoformat(),
        "end_at": row.end_at.astimezone(UTC).isoformat(),
        "timezone": row.timezone,
        "all_day": bool(row.all_day),
        "recurrence_rule": row.recurrence_rule,
        "reminder_minutes": list(row.reminder_minutes or []),
        "status": row.status,
        "source": row.source,
        "source_response_id": row.source_response_id,
        "revision": int(row.revision or 1),
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
    }


def _append_calendar_revision(
    db: AsyncSession,
    *,
    row: CalendarEvent,
    action: str,
    changed_fields: list[str],
    source: str,
    source_response_id: str | None,
) -> CalendarEventRevision:
    revision = CalendarEventRevision(
        id=str(uuid.uuid4()),
        event_id=row.id,
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        revision=int(row.revision or 1),
        action=action,
        snapshot=_calendar_snapshot(row),
        changed_fields=sorted(set(changed_fields)),
        source=source,
        source_response_id=source_response_id,
    )
    db.add(revision)
    return revision


async def get_scoped_calendar_event(
    db: AsyncSession,
    *,
    event_id: str,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    for_update: bool = False,
) -> CalendarEvent | None:
    statement = select(CalendarEvent).where(
        CalendarEvent.id == event_id,
        CalendarEvent.user_id == user_id,
        CalendarEvent.tenant_id == tenant_id,
        CalendarEvent.workspace_id == workspace_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def create_calendar_event_record(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    title: str,
    start_at: datetime | str,
    end_at: datetime | str,
    timezone_name: str,
    description: str = "",
    location: str = "",
    event_type: str = "event",
    all_day: bool = False,
    recurrence_rule: str | None = None,
    reminder_minutes: list[int] | None = None,
    source: str = "manual",
    source_response_id: str | None = None,
) -> CalendarEvent:
    timezone_name = ensure_timezone(timezone_name)
    start = parse_calendar_datetime(start_at, timezone_name)
    end = parse_calendar_datetime(end_at, timezone_name)
    validate_event_window(start, end, all_day=all_day, timezone_name=timezone_name)
    if event_type not in {"event", "meeting", "focus", "reminder"}:
        raise CalendarValidationError("invalid_event_type")
    normalized_title = title.strip()
    if not normalized_title:
        raise CalendarValidationError("calendar_title_required")
    row = CalendarEvent(
        id=str(uuid.uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        title=normalized_title[:255],
        description=description.strip(),
        location=location.strip()[:512],
        event_type=event_type,
        start_at=start,
        end_at=end,
        timezone=timezone_name,
        all_day=all_day,
        recurrence_rule=normalize_recurrence_rule(recurrence_rule),
        reminder_minutes=normalize_reminder_minutes(reminder_minutes),
        status="confirmed",
        source=source,
        source_response_id=source_response_id,
        revision=1,
    )
    db.add(row)
    # 修订表只有纯外键，必须先显式 flush 父事件。
    await db.flush()
    _append_calendar_revision(
        db,
        row=row,
        action="created",
        changed_fields=["created"],
        source=source,
        source_response_id=source_response_id,
    )
    return row


async def update_calendar_event_record(
    db: AsyncSession,
    *,
    row: CalendarEvent,
    changes: dict[str, Any],
    source: str,
    source_response_id: str | None = None,
) -> CalendarEvent:
    if row.status == "cancelled":
        raise CalendarValidationError("calendar_event_cancelled")
    allowed = {
        "title",
        "description",
        "location",
        "event_type",
        "start_at",
        "end_at",
        "timezone",
        "all_day",
        "recurrence_rule",
        "reminder_minutes",
    }
    changes = {key: value for key, value in changes.items() if key in allowed}
    timezone_name = ensure_timezone(str(changes.get("timezone") or row.timezone))
    duration = row.end_at - row.start_at
    start = (
        parse_calendar_datetime(changes["start_at"], timezone_name)
        if changes.get("start_at") is not None
        else row.start_at
    )
    if changes.get("end_at") is not None:
        end = parse_calendar_datetime(changes["end_at"], timezone_name)
    elif changes.get("start_at") is not None:
        end = start + duration
    else:
        end = row.end_at
    all_day = bool(changes.get("all_day", row.all_day))
    validate_event_window(start, end, all_day=all_day, timezone_name=timezone_name)

    normalized: dict[str, Any] = {
        "start_at": start,
        "end_at": end,
        "timezone": timezone_name,
        "all_day": all_day,
    }
    if "title" in changes:
        title = str(changes["title"] or "").strip()
        if not title:
            raise CalendarValidationError("calendar_title_required")
        normalized["title"] = title[:255]
    for field, limit in (("description", None), ("location", 512)):
        if field in changes:
            value = str(changes[field] or "").strip()
            normalized[field] = value[:limit] if limit else value
    if "event_type" in changes:
        event_type = str(changes["event_type"] or "")
        if event_type not in {"event", "meeting", "focus", "reminder"}:
            raise CalendarValidationError("invalid_event_type")
        normalized["event_type"] = event_type
    if "recurrence_rule" in changes:
        normalized["recurrence_rule"] = normalize_recurrence_rule(changes["recurrence_rule"])
    if "reminder_minutes" in changes:
        normalized["reminder_minutes"] = normalize_reminder_minutes(changes["reminder_minutes"])

    changed_fields = [field for field, value in normalized.items() if getattr(row, field) != value]
    if not changed_fields:
        return row
    for field, value in normalized.items():
        setattr(row, field, value)
    row.revision = int(row.revision or 1) + 1
    row.cancelled_at = None
    _append_calendar_revision(
        db,
        row=row,
        action="updated",
        changed_fields=changed_fields,
        source=source,
        source_response_id=source_response_id,
    )
    return row


async def cancel_calendar_event_record(
    db: AsyncSession,
    *,
    row: CalendarEvent,
    source: str,
    source_response_id: str | None = None,
    now: datetime | None = None,
) -> CalendarEvent:
    if row.status == "cancelled":
        return row
    cancelled_at = now or datetime.now(UTC)
    if cancelled_at.tzinfo is None:
        cancelled_at = cancelled_at.replace(tzinfo=UTC)
    row.status = "cancelled"
    row.cancelled_at = cancelled_at.astimezone(UTC)
    row.revision = int(row.revision or 1) + 1
    _append_calendar_revision(
        db,
        row=row,
        action="cancelled",
        changed_fields=["status", "cancelled_at"],
        source=source,
        source_response_id=source_response_id,
    )
    return row


async def calendar_event_history(
    db: AsyncSession,
    *,
    event_id: str,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    timezone_name: str = DEFAULT_CALENDAR_TIMEZONE,
) -> dict[str, Any] | None:
    row = await get_scoped_calendar_event(
        db,
        event_id=event_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if row is None:
        return None
    revisions = list(
        (
            await db.execute(
                select(CalendarEventRevision)
                .where(
                    CalendarEventRevision.event_id == event_id,
                    CalendarEventRevision.user_id == user_id,
                    CalendarEventRevision.tenant_id == tenant_id,
                    CalendarEventRevision.workspace_id == workspace_id,
                )
                .order_by(CalendarEventRevision.revision.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "event": event_to_dict(row, timezone_name=timezone_name),
        "revisions": [
            {
                "revision": revision.revision,
                "action": revision.action,
                "snapshot": revision.snapshot,
                "changed_fields": list(revision.changed_fields or []),
                "source": revision.source,
                "source_response_id": revision.source_response_id,
                "created_at": revision.created_at.isoformat() if revision.created_at else None,
            }
            for revision in revisions
        ],
    }


def _expanded_occurrences(
    row: CalendarEvent,
    *,
    start_at: datetime,
    end_at: datetime,
) -> list[tuple[datetime, datetime, str | None]]:
    duration = row.end_at - row.start_at
    if not row.recurrence_rule:
        if row.end_at <= start_at or row.start_at >= end_at:
            return []
        return [(row.start_at, row.end_at, None)]
    try:
        rule = rrulestr(row.recurrence_rule, dtstart=row.start_at)
    except (TypeError, ValueError):
        return []
    items: list[tuple[datetime, datetime, str | None]] = []
    cursor = start_at - duration
    for index in range(MAX_EXPANDED_EVENTS):
        occurrence = rule.after(cursor, inc=index == 0)
        if occurrence is None or occurrence >= end_at:
            break
        occurrence = occurrence if occurrence.tzinfo else occurrence.replace(tzinfo=UTC)
        occurrence = occurrence.astimezone(UTC)
        cursor = occurrence
        occurrence_end = occurrence + duration
        if occurrence_end <= start_at or occurrence >= end_at:
            continue
        items.append((occurrence, occurrence_end, f"{row.id}:{occurrence.isoformat()}"))
    return items


async def list_calendar_events(
    db: AsyncSession,
    *,
    user: User | None = None,
    user_id: str | None = None,
    tenant_id: str,
    workspace_id: str,
    start_at: datetime,
    end_at: datetime,
    timezone_name: str = DEFAULT_CALENDAR_TIMEZONE,
    limit: int = MAX_EXPANDED_EVENTS,
    include_cancelled: bool = False,
) -> list[dict[str, Any]]:
    if end_at <= start_at:
        raise CalendarValidationError("calendar_end_must_be_after_start")
    if user_id is None and user is not None:
        user_id = user.id
    if not user_id:
        raise CalendarValidationError("calendar_user_required")
    timezone_name = ensure_timezone(timezone_name)
    start_at = parse_calendar_datetime(start_at, timezone_name)
    end_at = parse_calendar_datetime(end_at, timezone_name)
    filters = [
        CalendarEvent.user_id == user_id,
        CalendarEvent.tenant_id == tenant_id,
        CalendarEvent.workspace_id == workspace_id,
        CalendarEvent.start_at < end_at,
        or_(CalendarEvent.end_at > start_at, CalendarEvent.recurrence_rule.is_not(None)),
    ]
    if not include_cancelled:
        filters.append(CalendarEvent.status != "cancelled")
    rows = list(
        (
            await db.execute(
                select(CalendarEvent)
                .where(*filters)
                .order_by(CalendarEvent.start_at.asc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    expanded: list[dict[str, Any]] = []
    for row in rows:
        for occurrence_start, occurrence_end, occurrence_id in _expanded_occurrences(
            row, start_at=start_at, end_at=end_at
        ):
            expanded.append(
                event_to_dict(
                    row,
                    timezone_name=timezone_name,
                    start_at=occurrence_start,
                    end_at=occurrence_end,
                    occurrence_id=occurrence_id,
                )
            )
            if len(expanded) >= min(max(limit, 1), MAX_EXPANDED_EVENTS):
                return sorted(expanded, key=lambda item: item["start_at"])
    return sorted(expanded, key=lambda item: item["start_at"])


async def upcoming_calendar_context(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    timezone_name: str = DEFAULT_CALENDAR_TIMEZONE,
    days: int = 14,
) -> list[dict[str, Any]]:
    zone = ZoneInfo(ensure_timezone(timezone_name))
    now = datetime.now(zone)
    start = now.astimezone(UTC)
    end = (now + timedelta(days=max(1, min(days, 31)))).astimezone(UTC)
    return await list_calendar_events(
        db,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        start_at=start,
        end_at=end,
        timezone_name=timezone_name,
        limit=40,
    )
