"""用户个人日历 API。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import CalendarEvent, User
from services.calendar import (
    DEFAULT_CALENDAR_TIMEZONE,
    CalendarValidationError,
    default_calendar_window,
    ensure_timezone,
    event_to_dict,
    list_calendar_events,
    normalize_recurrence_rule,
    parse_calendar_datetime,
    validate_event_window,
)

router = APIRouter()


class CalendarEventPayload(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=20_000)
    location: str = Field(default="", max_length=512)
    event_type: str = Field(default="event", pattern="^(event|meeting|focus|reminder)$")
    start_at: datetime
    end_at: datetime
    timezone: str = Field(default=DEFAULT_CALENDAR_TIMEZONE, max_length=64)
    all_day: bool = False
    recurrence_rule: str | None = Field(default=None, max_length=512)
    reminder_minutes: list[int] = Field(default_factory=lambda: [15], max_length=5)


class CalendarEventPatchPayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, max_length=512)
    event_type: str | None = Field(default=None, pattern="^(event|meeting|focus|reminder)$")
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=64)
    all_day: bool | None = None
    recurrence_rule: str | None = Field(default=None, max_length=512)
    reminder_minutes: list[int] | None = Field(default=None, max_length=5)


def _scope(request: Request, user: User) -> tuple[str, str]:
    return normalized_tenant_scope(build_tenant_metadata(request, user_id=user.id))


def _calendar_error(exc: CalendarValidationError) -> AppException:
    messages = {
        "event_end_must_be_after_start": "日程结束时间必须晚于开始时间",
        "all_day_event_must_use_midnight_boundary": "全天日程必须按自然日边界保存",
        "event_duration_too_long": "单个日程持续时间不能超过 366 天",
        "invalid_recurrence_rule": "重复规则无效",
        "unsupported_recurrence_frequency": "日历重复仅支持每天、每周、每月或每年",
        "calendar_end_must_be_after_start": "查询结束时间必须晚于开始时间",
    }
    code = str(exc)
    if code.startswith("invalid_timezone"):
        message = "时区无效"
    else:
        message = messages.get(code, "日历参数无效")
    return AppException(ErrorCodes.PARAM_INVALID.code, message=message)


def _normalize_reminders(values: list[int]) -> list[int]:
    normalized = sorted({int(value) for value in values if 0 <= int(value) <= 10080})
    if len(normalized) > 5:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="最多配置 5 个提醒时间")
    return normalized


async def _owned_event(
    db: AsyncSession,
    request: Request,
    user: User,
    event_id: str,
) -> CalendarEvent:
    tenant_id, workspace_id = _scope(request, user)
    row = await db.scalar(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.user_id == user.id,
            CalendarEvent.tenant_id == tenant_id,
            CalendarEvent.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="日程不存在")
    return row


@router.get("/calendar/events")
async def get_calendar_events(
    request: Request,
    start: datetime | None = None,
    end: datetime | None = None,
    timezone: str = Query(default=DEFAULT_CALENDAR_TIMEZONE, max_length=64),
    limit: int = Query(default=200, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    try:
        timezone = ensure_timezone(timezone)
        default_start, default_end = default_calendar_window(timezone)
        start_at = parse_calendar_datetime(start or default_start, timezone)
        end_at = parse_calendar_datetime(end or default_end, timezone)
        items = await list_calendar_events(
            db,
            user=current_user,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            start_at=start_at,
            end_at=end_at,
            timezone_name=timezone,
            limit=limit,
        )
    except CalendarValidationError as exc:
        raise _calendar_error(exc) from exc
    return {
        "scope": {"tenant_id": tenant_id, "workspace_id": workspace_id},
        "timezone": timezone,
        "start": start_at.isoformat(),
        "end": end_at.isoformat(),
        "items": items,
    }


@router.get("/calendar/events/{event_id}")
async def get_calendar_event(
    event_id: str,
    request: Request,
    timezone: str = Query(default=DEFAULT_CALENDAR_TIMEZONE, max_length=64),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _owned_event(db, request, current_user, event_id)
    try:
        return event_to_dict(row, timezone_name=ensure_timezone(timezone))
    except CalendarValidationError as exc:
        raise _calendar_error(exc) from exc


@router.post("/calendar/events")
async def create_calendar_event(
    request: Request,
    payload: CalendarEventPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    try:
        timezone = ensure_timezone(payload.timezone)
        start_at = parse_calendar_datetime(payload.start_at, timezone)
        end_at = parse_calendar_datetime(payload.end_at, timezone)
        validate_event_window(
            start_at,
            end_at,
            all_day=payload.all_day,
            timezone_name=timezone,
        )
        recurrence_rule = normalize_recurrence_rule(payload.recurrence_rule)
    except CalendarValidationError as exc:
        raise _calendar_error(exc) from exc
    row = CalendarEvent(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        location=payload.location.strip(),
        event_type=payload.event_type,
        start_at=start_at,
        end_at=end_at,
        timezone=timezone,
        all_day=payload.all_day,
        recurrence_rule=recurrence_rule,
        reminder_minutes=_normalize_reminders(payload.reminder_minutes),
        status="confirmed",
        source="manual",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return event_to_dict(row, timezone_name=timezone)


@router.patch("/calendar/events/{event_id}")
async def update_calendar_event(
    event_id: str,
    request: Request,
    payload: CalendarEventPatchPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _owned_event(db, request, current_user, event_id)
    changes = payload.model_dump(exclude_unset=True)
    try:
        timezone = ensure_timezone(str(changes.get("timezone") or row.timezone))
        start_at = parse_calendar_datetime(changes.get("start_at") or row.start_at, timezone)
        end_at = parse_calendar_datetime(changes.get("end_at") or row.end_at, timezone)
        all_day = bool(changes.get("all_day", row.all_day))
        validate_event_window(start_at, end_at, all_day=all_day, timezone_name=timezone)
        recurrence_rule = (
            normalize_recurrence_rule(changes.get("recurrence_rule"))
            if "recurrence_rule" in changes
            else row.recurrence_rule
        )
    except CalendarValidationError as exc:
        raise _calendar_error(exc) from exc
    row.start_at = start_at
    row.end_at = end_at
    row.timezone = timezone
    row.all_day = all_day
    row.recurrence_rule = recurrence_rule
    for field in ("title", "description", "location", "event_type"):
        if field in changes and changes[field] is not None:
            setattr(row, field, str(changes[field]).strip())
    if changes.get("reminder_minutes") is not None:
        row.reminder_minutes = _normalize_reminders(changes["reminder_minutes"])
    row.status = "confirmed"
    await db.commit()
    await db.refresh(row)
    return event_to_dict(row, timezone_name=timezone)


@router.delete("/calendar/events/{event_id}")
async def cancel_calendar_event(
    event_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _owned_event(db, request, current_user, event_id)
    row.status = "cancelled"
    await db.commit()
    return {"id": row.id, "status": "cancelled"}
