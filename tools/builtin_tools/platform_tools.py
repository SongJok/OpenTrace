"""Governed project automation tools exposed through the main Agent Loop."""

from __future__ import annotations

import json
import math
import uuid
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from infra.responses.scheduler import next_occurrence, parse_schedule_expression
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import AlertRule, ChatSession, DataSource, Project, TaskDefinition
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
            ).scalars().all()
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
            "schedule": {"type": "string", "description": "如 每天 09:00、每周一 10:30 或 FREQ=..."},
            "timezone": {"type": "string", "default": "Asia/Shanghai"},
            "enabled": {"type": "boolean", "default": False},
        },
        "required": ["title", "prompt", "schedule"],
    },
)
async def create_scheduled_task(
    title: str,
    prompt: str,
    schedule: str,
    timezone: str = "Asia/Shanghai",
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
        await _authorized_project(
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
            ).scalars().all()
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
            "aggregation": {"type": "string", "enum": ["first", "sum", "avg", "min", "max", "count"]},
            "operator": {"type": "string", "enum": ["gt", "gte", "lt", "lte", "eq", "neq", "change_pct_gt", "change_pct_lt"]},
            "threshold": {"type": "number"},
            "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
            "schedule": {"type": "string"},
            "timezone": {"type": "string", "default": "Asia/Shanghai"},
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
    timezone: str = "Asia/Shanghai",
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
        source = await db.scalar(
            select(DataSource).where(
                DataSource.id == data_source_id,
                DataSource.user_id == user_id,
                DataSource.tenant_id == tenant_id,
                DataSource.workspace_id == workspace_id,
                DataSource.status == "active",
            )
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
