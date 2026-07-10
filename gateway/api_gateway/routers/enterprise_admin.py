"""Enterprise admin — tenant, control plane, capability marketplace, compliance audit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from gateway.api_gateway.routers.admin import get_current_admin_user
from infra.storage.models import User

router = APIRouter()


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
    from tenant.usage_metering import get_usage_metering
    from tenant.billing_manager import BillingManager

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
