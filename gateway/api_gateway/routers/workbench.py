"""企业 AI 工作台 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User
from services.enterprise_workbench import enterprise_workbench_overview

router = APIRouter()


@router.get("/workbench/overview")
async def get_workbench_overview(
    request: Request,
    recent_limit: int = Query(default=6, ge=3, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    return await enterprise_workbench_overview(
        db,
        user=current_user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        recent_limit=recent_limit,
    )
