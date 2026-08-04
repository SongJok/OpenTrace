"""Governed project automation tools exposed through the main Agent Loop."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from infra.config.constants import DEFAULT_TIMEZONE
from infra.responses.scheduler import next_occurrence, parse_schedule_expression
from infra.security.resource_scope import get_accessible_data_source
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import AlertRule, ChatSession, Project, TaskDefinition
from services.calendar import (
    calendar_event_history,
    cancel_calendar_event_record,
    create_calendar_event_record,
    ensure_timezone,
    event_to_dict,
    get_scoped_calendar_event,
    parse_calendar_datetime,
    update_calendar_event_record,
)
from services.calendar import (
    list_calendar_events as query_calendar_events,
)
from tools.registry.registry import registry


def _schedule(value: str, timezone: str) -> str:
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid_timezone") from exc
    rule = value.strip()
    if not rule.upper().startswith("FREQ="):
        rule = parse_schedule_expression(rule)
    if next_occurrence(rule, timezone) is None:
        raise ValueError("schedule_has_no_next_occurrence")
    return rule


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", ""}:
            return False
        if normalized in {"true", "1", "yes"}:
            return True
    return bool(value)


def _as_int_list(value: Any, *, default: list[int]) -> list[int]:
    candidate = value
    if isinstance(value, str):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError):
            candidate = []
    if not isinstance(candidate, list):
        candidate = default
    return [int(item) for item in candidate]


async def _authorized_project(
    db: Any,
    *,
    project_id: str | None,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> Project | None:
    if not project_id:
        return None
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
            Project.tenant_id == tenant_id,
            Project.workspace_id == workspace_id,
            Project.archived_at.is_(None),
        )
    )
    if project is None:
        raise ValueError("project_not_authorized")
    return project


@registry.tool(
    name="list_scheduled_tasks",
    description="查询当前用户和工作区的定时 Agent 任务，包括状态和下次运行时间。",
    tags=["定时任务", "自动化", "schedule", "task", "list"],
    parameters={"type": "object", "properties": {}},
)
async def list_scheduled_tasks(
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(TaskDefinition)
                    .where(
                        TaskDefinition.user_id == user_id,
                        TaskDefinition.tenant_id == tenant_id,
                        TaskDefinition.workspace_id == workspace_id,
                    )
                    .order_by(TaskDefinition.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return {
            "status": "success",
            "items": [
                {
                    "id": row.id,
                    "title": row.title,
                    "prompt": row.description,
                    "status": row.status,
                    "rrule": row.rrule,
                    "timezone": row.timezone,
                    "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
                }
                for row in rows
            ],
        }


@registry.tool(
    name="create_scheduled_task",
    description="创建定时执行完整 Agent Loop 的任务。自然语言时间或 RRULE 均可；这是写操作，执行前必须由用户审批。",
    tags=["创建定时任务", "定时执行", "自动化", "schedule", "recurring"],
    side_effect="write",
    supports_parallel=False,
    max_retries=0,
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "prompt": {"type": "string", "description": "每次运行时交给主 Agent Loop 的完整任务"},
            "schedule": {
                "type": "string",
                "description": "如 每天 09:00、每周一 10:30 或 FREQ=...",
            },
            "timezone": {"type": "string", "default": DEFAULT_TIMEZONE},
            "enabled": {"type": "boolean", "default": False},
        },
        "required": ["title", "prompt", "schedule"],
    },
)
async def create_scheduled_task(
    title: str,
    prompt: str,
    schedule: str,
    timezone: str = DEFAULT_TIMEZONE,
    enabled: bool = False,
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    project_id: str | None = None,
    conversation_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    rule = _schedule(schedule, timezone)
    async with AsyncSessionLocal() as db:
        project = await _authorized_project(
            db,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        reusable_conversation = None
        if conversation_id:
            reusable_conversation = await db.scalar(
                select(ChatSession.id).where(
                    ChatSession.id == conversation_id,
                    ChatSession.user_id == user_id,
                    ChatSession.tenant_id == tenant_id,
                    ChatSession.workspace_id == workspace_id,
                    ChatSession.is_temporary.is_(False),
                )
            )
        row = TaskDefinition(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            conversation_id=reusable_conversation,
            title=title.strip()[:255],
            description=prompt.strip(),
            task_type="agent_task",
            task_config={
                "data_source_ids": [
                    str(item) for item in (project.data_source_ids if project else []) if str(item)
                ]
            },
            trigger_type="rrule",
            trigger_config_json=json.dumps({"rrule": rule, "timezone": timezone}),
            rrule=rule,
            timezone=timezone,
            requires_confirmation=True,
            status="active" if enabled else "draft",
            next_run_at=next_occurrence(rule, timezone) if enabled else None,
        )
        db.add(row)
        await db.commit()
        return {
            "status": "success",
            "task": {
                "id": row.id,
                "title": row.title,
                "status": row.status,
                "rrule": row.rrule,
                "timezone": row.timezone,
                "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
            },
        }


@registry.tool(
    name="list_data_alerts",
    description="查询当前用户和工作区的数据主动预警规则及其最近状态。",
    tags=["主动预警", "数据告警", "alert", "monitor", "list"],
    parameters={"type": "object", "properties": {}},
)
async def list_data_alerts(
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(AlertRule)
                    .where(
                        AlertRule.user_id == user_id,
                        AlertRule.tenant_id == tenant_id,
                        AlertRule.workspace_id == workspace_id,
                    )
                    .order_by(AlertRule.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return {
            "status": "success",
            "items": [
                {
                    "id": row.id,
                    "name": row.name,
                    "status": row.status,
                    "last_state": row.last_state,
                    "last_value": row.last_value,
                    "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
                    "last_error": row.last_error,
                }
                for row in rows
            ],
        }


@registry.tool(
    name="create_data_alert",
    description="创建受项目数据源权限治理的数据预警。取数由 Data Agent 完成，阈值由确定性代码判断；这是写操作，执行前必须审批。",
    tags=["创建预警", "主动预警", "数据告警", "阈值", "alert", "monitor"],
    side_effect="write",
    supports_parallel=False,
    max_retries=0,
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "question": {"type": "string", "description": "返回待判断数值的数据问题"},
            "data_source_id": {"type": "string"},
            "metric_column": {"type": "string"},
            "aggregation": {
                "type": "string",
                "enum": ["first", "sum", "avg", "min", "max", "count"],
            },
            "operator": {
                "type": "string",
                "enum": ["gt", "gte", "lt", "lte", "eq", "neq", "change_pct_gt", "change_pct_lt"],
            },
            "threshold": {"type": "number"},
            "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
            "schedule": {"type": "string"},
            "timezone": {"type": "string", "default": DEFAULT_TIMEZONE},
            "enabled": {"type": "boolean", "default": False},
        },
        "required": ["name", "question", "data_source_id", "operator", "threshold", "schedule"],
    },
)
async def create_data_alert(
    name: str,
    question: str,
    data_source_id: str,
    operator: str,
    threshold: float,
    schedule: str,
    metric_column: str = "",
    aggregation: str = "first",
    severity: str = "warning",
    timezone: str = DEFAULT_TIMEZONE,
    enabled: bool = False,
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    project_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    if not math.isfinite(float(threshold)):
        raise ValueError("invalid_threshold")
    if aggregation not in {"first", "sum", "avg", "min", "max", "count"}:
        raise ValueError("invalid_aggregation")
    if operator not in {"gt", "gte", "lt", "lte", "eq", "neq", "change_pct_gt", "change_pct_lt"}:
        raise ValueError("invalid_operator")
    if severity not in {"info", "warning", "critical"}:
        raise ValueError("invalid_severity")
    rule = _schedule(schedule, timezone)
    async with AsyncSessionLocal() as db:
        project = await _authorized_project(
            db,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        source = await get_accessible_data_source(
            db,
            user_id=user_id,
            tenant_metadata={"tenant_id": tenant_id, "workspace_id": workspace_id},
            data_source_id=data_source_id,
            required_permission="query",
            active_only=True,
        )
        if source is None:
            raise ValueError("data_source_not_authorized")
        if project is not None and data_source_id not in set(project.data_source_ids or []):
            raise ValueError("project_data_source_not_authorized")
        row = AlertRule(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            data_source_id=data_source_id,
            name=name.strip()[:255],
            question=question.strip(),
            metric_column=metric_column.strip() or None,
            aggregation=aggregation,
            operator=operator,
            threshold=float(threshold),
            severity=severity,
            rrule=rule,
            timezone=timezone,
            status="active" if enabled else "draft",
            next_run_at=next_occurrence(rule, timezone) if enabled else None,
        )
        db.add(row)
        await db.commit()
        return {
            "status": "success",
            "alert": {
                "id": row.id,
                "name": row.name,
                "status": row.status,
                "rrule": row.rrule,
                "timezone": row.timezone,
                "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
            },
        }


@registry.tool(
    name="list_calendar_events",
    description=(
        "查询当前用户个人日历。用户询问今天、明天、本周、下周安排或空闲时间时调用；"
        "start_at 和 end_at 使用 ISO-8601，未提供时查询未来 14 天。"
    ),
    tags=["日历", "日程", "安排", "今天", "明天", "本周", "calendar", "agenda"],
    parameters={
        "type": "object",
        "properties": {
            "start_at": {"type": "string", "description": "查询开始时间 ISO-8601"},
            "end_at": {"type": "string", "description": "查询结束时间 ISO-8601"},
            "timezone": {"type": "string", "description": "IANA 时区，如 Asia/Shanghai"},
            "include_cancelled": {
                "type": "boolean",
                "description": "仅在查询已取消安排或历史时设为 true",
            },
        },
        "required": [],
    },
)
async def list_calendar_events_tool(
    start_at: str = "",
    end_at: str = "",
    timezone: str = DEFAULT_TIMEZONE,
    include_cancelled: bool = False,
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    timezone = ensure_timezone(timezone)
    now = datetime.now(ZoneInfo(timezone))
    start = parse_calendar_datetime(start_at, timezone) if start_at else now.astimezone(UTC)
    end = (
        parse_calendar_datetime(end_at, timezone)
        if end_at
        else (now + timedelta(days=14)).astimezone(UTC)
    )
    async with AsyncSessionLocal() as db:
        items = await query_calendar_events(
            db,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            start_at=start,
            end_at=end,
            timezone_name=timezone,
            limit=100,
            include_cancelled=_as_bool(include_cancelled),
        )
    return {"status": "success", "timezone": timezone, "items": items}


@registry.tool(
    name="get_calendar_event_history",
    description=(
        "读取一个日历事件的创建、改期和取消修订历史。仅当用户询问日程是否取消、"
        "何时改期或原安排是什么时调用；先用 list_calendar_events 获取 event_id。"
    ),
    tags=["日程历史", "取消记录", "改期记录", "原安排", "calendar history"],
    parameters={
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "timezone": {"type": "string", "description": "IANA 时区"},
        },
        "required": ["event_id"],
    },
)
async def get_calendar_event_history_tool(
    event_id: str,
    timezone: str = DEFAULT_TIMEZONE,
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    timezone = ensure_timezone(timezone)
    async with AsyncSessionLocal() as db:
        history = await calendar_event_history(
            db,
            event_id=event_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            timezone_name=timezone,
        )
    if history is None:
        raise ValueError("calendar_event_not_found")
    return {"status": "success", **history}


@registry.tool(
    name="create_calendar_event",
    description=(
        "在当前用户个人日历中创建日程。仅当用户明确说“记录、添加到日历、提醒我、安排、预定”"
        "时调用；这是持久化写操作，执行前必须由用户审批。相对日期必须先按当前日期和 timezone "
        "换算成明确 ISO-8601 时间。"
    ),
    tags=[
        "添加日历",
        "记录日程",
        "提醒我",
        "安排会议",
        "预定日历",
        "预订会议",
        "明天要做",
        "calendar",
        "create event",
    ],
    side_effect="write",
    supports_parallel=False,
    max_retries=0,
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start_at": {"type": "string", "description": "开始时间 ISO-8601"},
            "end_at": {"type": "string", "description": "结束时间 ISO-8601；省略时默认 1 小时"},
            "timezone": {"type": "string", "description": "IANA 时区"},
            "description": {"type": "string"},
            "location": {"type": "string"},
            "event_type": {"type": "string", "enum": ["event", "meeting", "focus", "reminder"]},
            "all_day": {"type": "boolean"},
            "recurrence_rule": {"type": "string", "description": "可选 RFC5545 RRULE"},
            "reminder_minutes": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["title", "start_at"],
    },
)
async def create_calendar_event_tool(
    title: str,
    start_at: str,
    end_at: str = "",
    timezone: str = DEFAULT_TIMEZONE,
    description: str = "",
    location: str = "",
    event_type: str = "event",
    all_day: bool = False,
    recurrence_rule: str = "",
    reminder_minutes: list[int] | None = None,
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    response_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    timezone = ensure_timezone(timezone)
    description = str(description or "")
    location = str(location or "")
    event_type = str(event_type or "event")
    recurrence_rule = str(recurrence_rule or "")
    all_day = _as_bool(all_day)
    start = parse_calendar_datetime(start_at, timezone)
    end = (
        parse_calendar_datetime(end_at, timezone)
        if end_at
        else start + (timedelta(days=1) if all_day else timedelta(hours=1))
    )
    reminders = sorted(
        {value for value in _as_int_list(reminder_minutes, default=[15]) if 0 <= value <= 10080}
    )[:5]
    async with AsyncSessionLocal() as db:
        row = await create_calendar_event_record(
            db,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            title=title,
            description=description,
            location=location,
            event_type=event_type,
            start_at=start,
            end_at=end,
            timezone_name=timezone,
            all_day=all_day,
            recurrence_rule=recurrence_rule,
            reminder_minutes=reminders,
            source="assistant",
            source_response_id=response_id,
        )
        await db.commit()
        return {"status": "success", "event": event_to_dict(row, timezone_name=timezone)}


@registry.tool(
    name="update_calendar_event",
    description="更新当前用户个人日历中的已有日程；必须先查询并取得 event_id。写操作需要用户审批。",
    tags=["修改日程", "改时间", "日历更新", "reschedule", "calendar update"],
    side_effect="write",
    supports_parallel=False,
    max_retries=0,
    parameters={
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "title": {"type": "string"},
            "start_at": {"type": "string"},
            "end_at": {"type": "string"},
            "timezone": {"type": "string"},
            "description": {"type": "string"},
            "location": {"type": "string"},
        },
        "required": ["event_id"],
    },
)
async def update_calendar_event_tool(
    event_id: str,
    title: str = "",
    start_at: str = "",
    end_at: str = "",
    timezone: str = "",
    description: str = "",
    location: str = "",
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    response_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    title = str(title or "")
    start_at = str(start_at or "")
    end_at = str(end_at or "")
    description = str(description or "")
    location = str(location or "")
    async with AsyncSessionLocal() as db:
        row = await get_scoped_calendar_event(
            db,
            event_id=event_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            for_update=True,
        )
        if row is None:
            raise ValueError("calendar_event_not_found")
        changes: dict[str, Any] = {}
        if title.strip():
            changes["title"] = title
        if start_at:
            changes["start_at"] = start_at
        if end_at:
            changes["end_at"] = end_at
        if timezone:
            changes["timezone"] = timezone
        if description.strip():
            changes["description"] = description
        if location.strip():
            changes["location"] = location
        await update_calendar_event_record(
            db,
            row=row,
            changes=changes,
            source="assistant",
            source_response_id=response_id,
        )
        await db.commit()
        return {
            "status": "success",
            "event_id": row.id,
            "title": row.title,
            "revision": row.revision,
        }


@registry.tool(
    name="cancel_calendar_event",
    description="取消当前用户个人日历中的日程；必须先查询并取得 event_id。写操作需要用户审批。",
    tags=["删除日程", "取消日程", "calendar cancel", "calendar delete"],
    side_effect="destructive",
    supports_parallel=False,
    max_retries=0,
    parameters={
        "type": "object",
        "properties": {"event_id": {"type": "string"}},
        "required": ["event_id"],
    },
)
async def cancel_calendar_event_tool(
    event_id: str,
    user_id: str = "",
    tenant_id: str = "default",
    workspace_id: str = "default",
    response_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        row = await get_scoped_calendar_event(
            db,
            event_id=event_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            for_update=True,
        )
        if row is None:
            raise ValueError("calendar_event_not_found")
        await cancel_calendar_event_record(
            db,
            row=row,
            source="assistant",
            source_response_id=response_id,
        )
        await db.commit()
        return {
            "status": "success",
            "event_id": row.id,
            "event_status": "cancelled",
            "revision": row.revision,
        }
