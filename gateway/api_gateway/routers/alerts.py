from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import normalized_tenant_scope
from gateway.api_gateway.routers.agent_resources import _validate_schedule
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.alerts.scheduler import evaluate_alert_rule
from infra.errors import AppException, ErrorCodes
from infra.responses.scheduler import next_occurrence
from infra.security.resource_scope import get_accessible_data_source
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import AlertEvent, AlertRule, Project, User

router = APIRouter()


class AlertRulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=3, max_length=20_000)
    data_source_id: str
    project_id: str | None = None
    metric_column: str | None = Field(default=None, max_length=255)
    aggregation: str = Field(default="first", pattern="^(first|sum|avg|min|max|count)$")
    operator: str = Field(
        default="gt", pattern="^(gt|gte|lt|lte|eq|neq|change_pct_gt|change_pct_lt)$"
    )
    threshold: float = Field(allow_inf_nan=False)
    severity: str = Field(default="warning", pattern="^(info|warning|critical)$")
    rrule: str = Field(min_length=5, max_length=512)
    timezone: str = Field(default="UTC", max_length=64)
    cooldown_seconds: int = Field(default=3600, ge=0, le=604800)
    enabled: bool = False


def _rule(row: AlertRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "question": row.question,
        "data_source_id": row.data_source_id,
        "project_id": row.project_id,
        "metric_column": row.metric_column,
        "aggregation": row.aggregation,
        "operator": row.operator,
        "threshold": row.threshold,
        "severity": row.severity,
        "rrule": row.rrule,
        "timezone": row.timezone,
        "status": row.status,
        "cooldown_seconds": row.cooldown_seconds,
        "last_value": row.last_value,
        "last_state": row.last_state,
        "last_error": row.last_error,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "last_triggered_at": row.last_triggered_at.isoformat() if row.last_triggered_at else None,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
    }


async def _owned_rule(db: AsyncSession, request: Request, user: User, rule_id: str) -> AlertRule:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=user.id)
    )
    row = await db.scalar(
        select(AlertRule).where(
            AlertRule.id == rule_id,
            AlertRule.user_id == user.id,
            AlertRule.tenant_id == tenant_id,
            AlertRule.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="预警规则不存在")
    return row


@router.get("/alerts/rules")
async def list_alert_rules(
    request: Request,
    project_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    stmt = select(AlertRule).where(
        AlertRule.user_id == current_user.id,
        AlertRule.tenant_id == tenant_id,
        AlertRule.workspace_id == workspace_id,
    )
    if project_id:
        stmt = stmt.where(AlertRule.project_id == project_id)
    rows = (await db.execute(stmt.order_by(AlertRule.created_at.desc()))).scalars().all()
    return {"items": [_rule(row) for row in rows]}


@router.post("/alerts/rules")
async def create_alert_rule(
    request: Request,
    payload: AlertRulePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _validate_schedule(payload.rrule, payload.timezone)
    tenant_md = build_tenant_metadata(request, user_id=current_user.id)
    tenant_id, workspace_id = normalized_tenant_scope(tenant_md)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata=tenant_md,
        data_source_id=payload.data_source_id,
        required_permission="query",
        active_only=True,
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="数据源不存在或不可用")
    if payload.project_id:
        project = await db.scalar(
            select(Project).where(
                Project.id == payload.project_id,
                Project.user_id == current_user.id,
                Project.tenant_id == tenant_id,
                Project.workspace_id == workspace_id,
                Project.archived_at.is_(None),
            )
        )
        if project is None or payload.data_source_id not in set(project.data_source_ids or []):
            raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="Project 未授权该数据源")
    row = AlertRule(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        status="active" if payload.enabled else "draft",
        next_run_at=next_occurrence(payload.rrule, payload.timezone) if payload.enabled else None,
        **payload.model_dump(exclude={"enabled"}),
    )
    db.add(row)
    await db.commit()
    return _rule(row)


@router.post("/alerts/rules/{rule_id}/actions/{action}")
async def alert_rule_action(
    rule_id: str,
    action: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if action not in {"enable", "pause", "cancel"}:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="不支持的预警操作")
    row = await _owned_rule(db, request, current_user, rule_id)
    row.status = {"enable": "active", "pause": "paused", "cancel": "cancelled"}[action]
    if action == "enable":
        row.next_run_at = next_occurrence(row.rrule, row.timezone, after=datetime.now(UTC))
    else:
        row.next_run_at = None
    await db.commit()
    return _rule(row)


@router.post("/alerts/rules/{rule_id}/test")
async def test_alert_rule(
    rule_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _owned_rule(db, request, current_user, rule_id)
    previous_status = row.status
    row.status = "active"
    await db.commit()
    try:
        return await evaluate_alert_rule(rule_id)
    finally:
        refreshed = await db.get(AlertRule, rule_id, populate_existing=True)
        if refreshed is not None:
            refreshed.status = previous_status
            if previous_status != "active":
                refreshed.next_run_at = None
            await db.commit()


@router.get("/alerts/events")
async def list_alert_events(
    request: Request,
    rule_id: str | None = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    rule_ids = select(AlertRule.id).where(
        AlertRule.user_id == current_user.id,
        AlertRule.tenant_id == tenant_id,
        AlertRule.workspace_id == workspace_id,
    )
    stmt = select(AlertEvent).where(
        AlertEvent.user_id == current_user.id, AlertEvent.rule_id.in_(rule_ids)
    )
    if rule_id:
        stmt = stmt.where(AlertEvent.rule_id == rule_id)
    rows = (
        (
            await db.execute(
                stmt.order_by(AlertEvent.created_at.desc()).limit(max(1, min(limit, 500)))
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "rule_id": row.rule_id,
                "state": row.state,
                "severity": row.severity,
                "value": row.value,
                "threshold": row.threshold,
                "summary": row.summary,
                "evidence": row.evidence,
                "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.post("/alerts/events/{event_id}/acknowledge")
async def acknowledge_alert_event(
    event_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    event = await db.scalar(
        select(AlertEvent)
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .where(
            AlertEvent.id == event_id,
            AlertEvent.user_id == current_user.id,
            AlertRule.tenant_id == tenant_id,
            AlertRule.workspace_id == workspace_id,
        )
    )
    if event is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="预警事件不存在")
    event.acknowledged_by = current_user.id
    event.acknowledged_at = datetime.now(UTC)
    await db.commit()
    return {"acknowledged": True, "id": event.id}
