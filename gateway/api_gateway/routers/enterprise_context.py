"""员工可见的企业认知上下文投影。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User
from services.enterprise_cognition import load_enterprise_context

router = APIRouter()


@router.get("/enterprise-context/current")
async def current_enterprise_context(
    request: Request,
    query: str = Query(default="公司和部门概况", max_length=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    metadata = build_tenant_metadata(request, user_id=current_user.id)
    tenant_id, workspace_id = normalized_tenant_scope(metadata)
    bundle = await load_enterprise_context(
        db,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        org_id=str(metadata.get("org_id") or tenant_id),
        query=query,
    )
    return {
        "vision": "成为企业级的工作台、最懂公司的 AI",
        "scope": {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "org_id": str(metadata.get("org_id") or tenant_id),
        },
        "entities": bundle.entities,
        "knowledge_space_ids": bundle.knowledge_space_ids,
        "requires_grounding": bundle.requires_grounding,
    }
