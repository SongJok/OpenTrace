"""Inject tenant/org/workspace from headers into request.state."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from infra.observability.logger import get_logger
from tenant.tenant_context import resolve_tenant_context
from tenant.tenant_manager import TenantManager, TenantRecord

logger = get_logger(__name__)


def tenant_headers_from_request(request: Request) -> dict[str, Any]:
    h = request.headers
    return {
        "tenant_id": h.get("x-tenant-id") or h.get("X-Tenant-Id"),
        "org_id": h.get("x-org-id") or h.get("X-Org-Id"),
        "workspace_id": h.get("x-workspace-id") or h.get("X-Workspace-Id"),
        "data_residency": h.get("x-data-residency") or h.get("X-Data-Residency"),
    }


def ensure_tenant_registered(tenant_id: str, *, tier: str = "standard") -> None:
    tm = TenantManager()
    if not tm.get(tenant_id):
        rec = TenantRecord(
            tenant_id=tenant_id,
            name=tenant_id,
            tier=tier,
        )
        tm.register(rec)
        try:
            import asyncio

            from tenant.tenant_store import upsert_tenant_record

            async def _persist() -> None:
                await upsert_tenant_record(rec)

            try:
                asyncio.get_running_loop().create_task(_persist())
            except RuntimeError:
                asyncio.run(_persist())
        except Exception as exc:
            logger.warning("tenant_record_persist_skipped", tenant_id=tenant_id, error=str(exc))


def build_tenant_metadata(request: Request, user_id: str | None = None) -> dict[str, Any]:
    hdr = tenant_headers_from_request(request)
    md: dict[str, Any] = {k: v for k, v in hdr.items() if v}
    if user_id:
        md["user_id"] = user_id
    tid = str(md.get("tenant_id") or "default")
    ensure_tenant_registered(tid)
    ctx = resolve_tenant_context(user_id=user_id, metadata=md)
    try:
        from tenant.policy_manager import PolicyManager

        md = PolicyManager().apply_to_metadata(ctx, ctx.to_dict())
        return md
    except Exception as exc:
        logger.warning("tenant_policy_apply_skipped", error=str(exc))
        return ctx.to_dict()