"""Enterprise admin — tenant, directory, operations, capabilities and compliance."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.admin import get_current_admin_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    EnterpriseDirectoryMembership,
    EnterpriseDirectoryPrincipal,
    EnterpriseDirectorySyncRun,
    User,
)
from services.enterprise_directory import (
    directory_membership_payload,
    directory_principal_payload,
    directory_sync_run_payload,
    sync_enterprise_directory,
)
from services.enterprise_operations import enterprise_operations_overview

router = APIRouter()


class DirectoryPrincipalInput(BaseModel):
    principal_type: Literal["department", "group", "role"]
    external_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    parent_external_id: str | None = Field(default=None, max_length=128)
    status: Literal["active", "inactive"] = "active"
    attributes: dict[str, Any] = Field(default_factory=dict)


class DirectoryMembershipInput(BaseModel):
    user_email: str = Field(min_length=3, max_length=255)
    principal_type: Literal["department", "group", "role"]
    principal_external_id: str = Field(min_length=1, max_length=128)
    status: Literal["active", "inactive"] = "active"
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DirectorySyncRequest(BaseModel):
    provider: Literal["manual", "scim", "hr"] = "manual"
    cursor: str | None = Field(default=None, max_length=512)
    authoritative: bool = False
    principals: list[DirectoryPrincipalInput] = Field(default_factory=list, max_length=2000)
    memberships: list[DirectoryMembershipInput] = Field(default_factory=list, max_length=5000)


def _scope(request: Request, user: User) -> tuple[str, str]:
    return normalized_tenant_scope(build_tenant_metadata(request, user_id=user.id))


@router.get("/admin/enterprise/operations/overview")
async def operations_overview(
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    return await enterprise_operations_overview(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )


@router.get("/admin/enterprise/directory/principals")
async def list_directory_principals(
    request: Request,
    principal_type: Literal["department", "group", "role"] | None = None,
    status: Literal["active", "inactive"] | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    stmt = select(EnterpriseDirectoryPrincipal).where(
        EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
        EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
    )
    if principal_type:
        stmt = stmt.where(EnterpriseDirectoryPrincipal.principal_type == principal_type)
    if status:
        stmt = stmt.where(EnterpriseDirectoryPrincipal.status == status)
    rows = list(
        (
            await db.execute(
                stmt.order_by(
                    EnterpriseDirectoryPrincipal.principal_type,
                    EnterpriseDirectoryPrincipal.display_name,
                ).limit(limit)
            )
        ).scalars()
    )
    return {"items": [directory_principal_payload(row) for row in rows]}


@router.get("/admin/enterprise/directory/memberships")
async def list_directory_memberships(
    request: Request,
    status: Literal["active", "inactive"] | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    stmt = (
        select(EnterpriseDirectoryMembership, User, EnterpriseDirectoryPrincipal)
        .join(User, EnterpriseDirectoryMembership.user_id == User.id)
        .join(
            EnterpriseDirectoryPrincipal,
            EnterpriseDirectoryMembership.principal_id == EnterpriseDirectoryPrincipal.id,
        )
        .where(
            EnterpriseDirectoryMembership.tenant_id == tenant_id,
            EnterpriseDirectoryMembership.workspace_id == workspace_id,
            EnterpriseDirectoryPrincipal.tenant_id == tenant_id,
            EnterpriseDirectoryPrincipal.workspace_id == workspace_id,
        )
    )
    if status:
        stmt = stmt.where(EnterpriseDirectoryMembership.status == status)
    rows = (
        await db.execute(
            stmt.order_by(
                EnterpriseDirectoryPrincipal.display_name,
                User.email,
            ).limit(limit)
        )
    ).all()
    return {
        "items": [
            directory_membership_payload(membership, user=user, principal=principal)
            for membership, user, principal in rows
        ]
    }


@router.get("/admin/enterprise/directory/sync-runs")
async def list_directory_sync_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    rows = list(
        (
            await db.execute(
                select(EnterpriseDirectorySyncRun)
                .where(
                    EnterpriseDirectorySyncRun.tenant_id == tenant_id,
                    EnterpriseDirectorySyncRun.workspace_id == workspace_id,
                )
                .order_by(EnterpriseDirectorySyncRun.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return {"items": [directory_sync_run_payload(row) for row in rows]}


@router.post("/admin/enterprise/directory/sync", status_code=202)
async def sync_directory(
    request: Request,
    payload: DirectorySyncRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = _scope(request, current_user)
    run = await sync_enterprise_directory(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor=current_user,
        provider=payload.provider,
        cursor=payload.cursor,
        authoritative=payload.authoritative,
        principals=[item.model_dump() for item in payload.principals],
        memberships=[item.model_dump() for item in payload.memberships],
    )
    await db.commit()
    await db.refresh(run)
    return directory_sync_run_payload(run)


@router.get("/admin/enterprise/tenants")
async def list_enterprise_tenants(
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from tenant.tenant_manager import TenantManager

    tm = TenantManager()
    return {"tenants": [t.to_dict() for t in tm.list_all()]}


@router.get("/admin/enterprise/control-plane/health")
async def control_plane_health(
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from control_plane.control_plane import get_enterprise_control_plane
    from kernel.capability_runtime.capability_os import get_capability_os

    cp = get_enterprise_control_plane()
    d = cp.evaluate_turn(session_id="health-check")
    return {
        "control_plane": {"sample_decision_allowed": d.allowed},
        "capability_marketplace_count": len(get_capability_os().list_marketplace()),
    }


@router.get("/admin/enterprise/capabilities/marketplace")
async def capability_marketplace(
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from kernel.capability_runtime.capability_os import get_capability_os

    return {"products": get_capability_os().list_marketplace()}


@router.get("/admin/enterprise/compliance/audit")
async def compliance_audit_recent(
    tenant_id: str = Query("default"),
    limit: int = Query(50, le=200),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from governance.compliance_audit_store import list_recent_events_from_db

    return {"events": await list_recent_events_from_db(tenant_id, limit=limit)}


@router.get("/admin/enterprise/usage/{tenant_id}")
async def tenant_usage_summary(
    tenant_id: str,
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from tenant.billing_manager import BillingManager
    from tenant.usage_metering import get_usage_metering

    usage = await get_usage_metering().tenant_summary_async(tenant_id)
    billing = BillingManager().snapshot(tenant_id)
    return {"usage": usage, "billing": billing}


@router.post("/admin/enterprise/tenants/{tenant_id}/quota")
async def set_tenant_quota(
    tenant_id: str,
    body: dict[str, Any],
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    from control_plane.control_plane import get_enterprise_control_plane
    from tenant.tenant_context import resolve_tenant_context

    ctx = resolve_tenant_context(
        tenant_id=tenant_id,
        org_id=str(body.get("org_id") or tenant_id),
        workspace_id=str(body.get("workspace_id") or "default"),
    )
    get_enterprise_control_plane().set_quota_limits(
        ctx,
        daily_turns=int(body.get("daily_turns", 10_000)),
        daily_cost=float(body.get("daily_cost", 500.0)),
    )
    return {"ok": True, "isolation_key": ctx.isolation_key()}
