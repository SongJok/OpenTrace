"""企业数据洞察、月报和经营简报 API。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.config.constants import DEFAULT_TIMEZONE
from infra.errors import AppException, ErrorCodes
from infra.responses.scheduler import next_occurrence
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import Project, TaskDefinition, TaskRun, User
from services.enterprise_reports import (
    REPORT_TASK_TYPE,
    REPORT_TEMPLATES,
    build_report_prompt,
    build_report_task_config,
    get_report_template,
)

router = APIRouter()


class EnterpriseReportPayload(BaseModel):
    report_type: str = Field(pattern="^(data_insight|monthly_report|management_brief)$")
    title: str = Field(min_length=1, max_length=255)
    objective: str = Field(default="", max_length=12_000)
    audience: str = Field(default="经营管理团队", max_length=255)
    project_id: str = Field(min_length=1, max_length=64)
    data_source_ids: list[str] = Field(min_length=1, max_length=10)
    include_knowledge: bool = False
    rrule: str | None = Field(default=None, max_length=512)
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    enabled: bool = False


def _scope(request: Request, user: User) -> tuple[str, str]:
    metadata = build_tenant_metadata(request, user_id=user.id)
    return (
        str(metadata.get("tenant_id") or "default"),
        str(metadata.get("workspace_id") or "default"),
    )


def _validate_schedule(rrule_value: str, timezone_name: str) -> None:
    try:
        zone = ZoneInfo(timezone_name)
        from dateutil.rrule import rrulestr  # type: ignore[import-untyped]

        rrulestr(rrule_value, dtstart=datetime.now(zone))
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="无效的报告运行时间") from exc


def _normalize_time(value: datetime | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    zone = ZoneInfo(timezone_name)
    localized = value.replace(tzinfo=zone) if value.tzinfo is None else value
    return localized.astimezone(UTC)


def _report_item(row: TaskDefinition) -> dict[str, Any]:
    try:
        trigger_config = json.loads(row.trigger_config_json or "{}")
    except (TypeError, ValueError):
        trigger_config = {}
    return {
        "id": row.id,
        "title": row.title,
        "report_type": dict(row.task_config or {}).get("report_type"),
        "task_config": dict(row.task_config or {}),
        "project_id": row.project_id,
        "rrule": row.rrule,
        "timezone": row.timezone,
        "starts_at": trigger_config.get("starts_at"),
        "ends_at": trigger_config.get("ends_at"),
        "status": row.status,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _report_run(run: TaskRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "response_id": run.response_id,
        "scheduled_for": run.scheduled_for.isoformat() if run.scheduled_for else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "output": run.output,
        "output_metadata": dict(run.output_metadata or {}),
        "error": run.error,
    }


@router.get("/reports/templates")
async def list_report_templates(current_user: User = Depends(get_current_user)):
    return {"items": [template.to_dict() for template in REPORT_TEMPLATES.values()]}


@router.get("/reports")
async def list_enterprise_reports(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    rows = list(
        (
            await db.execute(
                select(TaskDefinition)
                .where(
                    TaskDefinition.user_id == current_user.id,
                    TaskDefinition.tenant_id == tenant_id,
                    TaskDefinition.workspace_id == workspace_id,
                    TaskDefinition.task_type == REPORT_TASK_TYPE,
                )
                .order_by(TaskDefinition.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_report_item(row) for row in rows]}


@router.post("/reports")
async def create_enterprise_report(
    payload: EnterpriseReportPayload,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    template = get_report_template(payload.report_type)
    rrule_value = (payload.rrule or template.default_rrule).strip()
    _validate_schedule(rrule_value, payload.timezone)
    starts_at = _normalize_time(payload.starts_at, payload.timezone)
    ends_at = _normalize_time(payload.ends_at, payload.timezone)
    if starts_at and ends_at and ends_at <= starts_at:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="结束时间必须晚于开始时间")

    project = await db.scalar(
        select(Project).where(
            Project.id == payload.project_id,
            Project.user_id == current_user.id,
            Project.tenant_id == tenant_id,
            Project.workspace_id == workspace_id,
            Project.archived_at.is_(None),
        )
    )
    if project is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Project 不存在或无权限")
    source_ids = list(dict.fromkeys(str(item) for item in payload.data_source_ids if str(item)))
    outside_project = sorted(
        set(source_ids) - {str(item) for item in project.data_source_ids or []}
    )
    if outside_project:
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code,
            message="报告数据源不在当前 Project 授权范围内",
            details={"data_source_ids": outside_project},
        )
    data_sources: list[dict[str, str]] = []
    tenant_metadata = {"tenant_id": tenant_id, "workspace_id": workspace_id}
    for source_id in source_ids:
        source = await get_accessible_data_source(
            db,
            user_id=current_user.id,
            tenant_metadata=tenant_metadata,
            data_source_id=source_id,
            required_permission="query",
            active_only=True,
        )
        if source is None or getattr(source, "status", "active") != "active":
            raise AppException(
                ErrorCodes.RESOURCE_NOT_FOUND.code,
                message="数据源不存在、未启用或无查询权限",
            )
        data_sources.append(
            {
                "id": str(source.id),
                "name": str(source.name),
                "type": str(getattr(source, "source_type", "database")),
            }
        )

    task_config = build_report_task_config(
        report_type=payload.report_type,
        objective=payload.objective,
        data_sources=data_sources,
        include_knowledge=payload.include_knowledge,
        audience=payload.audience,
    )
    row = TaskDefinition(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        title=payload.title,
        description=build_report_prompt(task_config),
        task_type=REPORT_TASK_TYPE,
        task_config=task_config,
        trigger_type="rrule",
        trigger_config_json=json.dumps(
            {
                "rrule": rrule_value,
                "timezone": payload.timezone,
                "starts_at": starts_at.isoformat() if starts_at else None,
                "ends_at": ends_at.isoformat() if ends_at else None,
            }
        ),
        status="active" if payload.enabled else "draft",
        rrule=rrule_value,
        timezone=payload.timezone,
        project_id=project.id,
        requires_confirmation=True,
        next_run_at=(
            next_occurrence(
                rrule_value,
                payload.timezone,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            if payload.enabled
            else None
        ),
    )
    if payload.enabled and row.next_run_at is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="报告有效期内没有可执行时间")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _report_item(row)


@router.get("/reports/{task_id}")
async def get_enterprise_report(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, workspace_id = _scope(request, current_user)
    row = await db.scalar(
        select(TaskDefinition).where(
            TaskDefinition.id == task_id,
            TaskDefinition.user_id == current_user.id,
            TaskDefinition.tenant_id == tenant_id,
            TaskDefinition.workspace_id == workspace_id,
            TaskDefinition.task_type == REPORT_TASK_TYPE,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="企业报告不存在")
    runs = list(
        (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.task_id == task_id)
                .order_by(TaskRun.started_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return {**_report_item(row), "runs": [_report_run(run) for run in runs]}
