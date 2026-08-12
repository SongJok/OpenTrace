"""Resource-level ACL management for governed shared assets."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import normalized_tenant_scope
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.security.identity import is_enterprise_admin
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import DataSource, ResourcePermission, User

router = APIRouter()


class PermissionGrantRequest(BaseModel):
    subject_user_id: str = Field(min_length=1, max_length=36)
    resource_type: str = Field(pattern="^data_source$")
    resource_id: str = Field(min_length=1, max_length=64)
    permission: str = Field(pattern="^(view|query|edit|admin)$")
    expires_at: datetime | None = None


class DataSourceAccessPolicyRequest(BaseModel):
    access_mode: str = Field(pattern="^(workspace|restricted)$")


@router.get("/resource-permissions/subjects")
async def list_permission_subjects(
    q: str = Query(default="", max_length=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(User).where(User.status == "active", User.id != current_user.id)
    if q.strip():
        term = f"%{q.strip()}%"
        from sqlalchemy import or_

        stmt = stmt.where(or_(User.email.ilike(term), User.display_name.ilike(term)))
    rows = list((await db.execute(stmt.order_by(User.email).limit(50))).scalars().all())
    return {
        "items": [
            {"id": row.id, "email": row.email, "display_name": row.display_name} for row in rows
        ]
    }


async def _require_resource_admin(
    db: AsyncSession,
    user: User,
    tenant_id: str,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
) -> None:
    if is_enterprise_admin(user) and resource_type == "data_source":
        return
    raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="只有管理员可以管理数据库权限")


@router.get("/resource-permissions")
async def list_resource_permissions(
    request: Request,
    resource_type: str = Query(pattern="^data_source$"),
    resource_id: str = Query(min_length=1, max_length=64),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    await _require_resource_admin(
        db, current_user, tenant_id, workspace_id, resource_type, resource_id
    )
    source = await db.scalar(
        select(DataSource).where(
            DataSource.id == resource_id,
            DataSource.tenant_id == tenant_id,
            DataSource.workspace_id == workspace_id,
        )
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="数据库不存在")
    rows = list(
        (
            await db.execute(
                select(ResourcePermission, User)
                .join(User, ResourcePermission.subject_user_id == User.id)
                .where(
                    ResourcePermission.tenant_id == tenant_id,
                    ResourcePermission.workspace_id == workspace_id,
                    ResourcePermission.resource_type == resource_type,
                    ResourcePermission.resource_id == resource_id,
                )
                .order_by(User.email)
            )
        ).all()
    )
    return {
        "access_mode": source.access_mode,
        "items": [
            {
                "id": permission.id,
                "subject_user_id": permission.subject_user_id,
                "subject_email": user.email,
                "permission": permission.permission,
                "expires_at": permission.expires_at.isoformat() if permission.expires_at else None,
                "granted_by": permission.granted_by,
            }
            for permission, user in rows
        ],
    }


@router.patch("/resource-permissions/data-sources/{resource_id}/access-mode")
async def update_data_source_access_mode(
    resource_id: str,
    request: Request,
    payload: DataSourceAccessPolicyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    await _require_resource_admin(
        db, current_user, tenant_id, workspace_id, "data_source", resource_id
    )
    source = await db.scalar(
        select(DataSource).where(
            DataSource.id == resource_id,
            DataSource.tenant_id == tenant_id,
            DataSource.workspace_id == workspace_id,
        )
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="数据库不存在")
    source.access_mode = payload.access_mode
    await db.commit()
    return {"resource_id": source.id, "access_mode": source.access_mode}


@router.post("/resource-permissions")
async def grant_resource_permission(
    request: Request,
    payload: PermissionGrantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    await _require_resource_admin(
        db, current_user, tenant_id, workspace_id, payload.resource_type, payload.resource_id
    )
    subject = await db.get(User, payload.subject_user_id)
    if subject is None or subject.status != "active":
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="被授权用户不存在或未启用")
    row = await db.scalar(
        select(ResourcePermission).where(
            ResourcePermission.tenant_id == tenant_id,
            ResourcePermission.workspace_id == workspace_id,
            ResourcePermission.subject_user_id == payload.subject_user_id,
            ResourcePermission.resource_type == payload.resource_type,
            ResourcePermission.resource_id == payload.resource_id,
        )
    )
    if row is None:
        row = ResourcePermission(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            subject_user_id=payload.subject_user_id,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            granted_by=current_user.id,
        )
        db.add(row)
    row.permission = payload.permission
    row.expires_at = payload.expires_at.astimezone(UTC) if payload.expires_at else None
    row.granted_by = current_user.id
    await db.commit()
    return {"id": row.id, "permission": row.permission}


@router.delete("/resource-permissions/{permission_id}")
async def revoke_resource_permission(
    permission_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    row = await db.get(ResourcePermission, permission_id)
    if row is None or row.tenant_id != tenant_id or row.workspace_id != workspace_id:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="授权记录不存在")
    await _require_resource_admin(
        db, current_user, tenant_id, workspace_id, row.resource_type, row.resource_id
    )
    await db.delete(row)
    await db.commit()
    return {"revoked": True, "id": permission_id}
