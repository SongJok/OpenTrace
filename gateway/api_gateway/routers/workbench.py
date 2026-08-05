"""企业 AI 工作台 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.config.constants import DEFAULT_TIMEZONE
from infra.errors import AppException, ErrorCodes
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User
from services.calendar import CalendarValidationError, ensure_timezone
from services.enterprise_workbench import enterprise_workbench_overview

router = APIRouter()


@router.get("/workbench/overview")
async def get_workbench_overview(
    request: Request,
    recent_limit: int = Query(default=6, ge=3, le=20),
    attention_limit: int = Query(default=10, ge=5, le=100),
    timezone: str = Query(default=DEFAULT_TIMEZONE, max_length=64),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    metadata = build_tenant_metadata(request, user_id=current_user.id)
    tenant_id, workspace_id = normalized_tenant_scope(metadata)
    try:
        timezone_name = ensure_timezone(timezone)
    except CalendarValidationError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="无效的工作台时区") from exc
    return await enterprise_workbench_overview(
        db,
        user=current_user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        org_id=str(metadata.get("org_id") or tenant_id),
        recent_limit=recent_limit,
        attention_limit=attention_limit,
        timezone_name=timezone_name,
    )
