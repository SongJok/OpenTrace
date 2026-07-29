"""个人日历领域服务。

日历是用户的一级记忆资源，而不是定时任务的别名：事件记录事实时间、时区和重复规则，
查询时再按用户视图展开实例。所有调用方必须先完成 user、tenant、workspace 作用域过滤。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import CalendarEvent, User

DEFAULT_CALENDAR_TIMEZONE = "Asia/Shanghai"
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
        "source": row.source,
        "source_response_id": row.source_response_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
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
    rows = list(
        (
            await db.execute(
                select(CalendarEvent)
                .where(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.tenant_id == tenant_id,
                    CalendarEvent.workspace_id == workspace_id,
                    CalendarEvent.status != "cancelled",
                    CalendarEvent.start_at < end_at,
                    or_(
                        CalendarEvent.end_at > start_at, CalendarEvent.recurrence_rule.is_not(None)
                    ),
                )
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
