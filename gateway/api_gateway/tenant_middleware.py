"""Inject tenant/org/workspace from headers into request.state."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from fastapi import Request

from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
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


def _tenant_signature_payload(
    *,
    user_id: str | None,
    tenant_id: str,
    org_id: str,
    workspace_id: str,
    data_residency: str,
    timestamp: str,
) -> bytes:
    values = (
        user_id or "",
        tenant_id,
        org_id,
        workspace_id,
        data_residency,
        timestamp,
    )
    return "\n".join(values).encode("utf-8")


def sign_tenant_headers(
    *,
    user_id: str | None,
    tenant_id: str = "default",
    org_id: str = "default",
    workspace_id: str = "default",
    data_residency: str = "",
    timestamp: int | None = None,
    secret: str | None = None,
) -> dict[str, str]:
    """Build headers for a trusted reverse proxy or integration test."""
    signing_secret = str(secret if secret is not None else settings.trusted_tenant_header_secret)
    if not signing_secret:
        raise ValueError("trusted tenant header secret is not configured")
    ts = str(int(timestamp if timestamp is not None else time.time()))
    payload = _tenant_signature_payload(
        user_id=user_id,
        tenant_id=tenant_id,
        org_id=org_id,
        workspace_id=workspace_id,
        data_residency=data_residency,
        timestamp=ts,
    )
    signature = hmac.new(signing_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    headers = {
        "X-Tenant-Id": tenant_id,
        "X-Org-Id": org_id,
        "X-Workspace-Id": workspace_id,
        "X-Tenant-Timestamp": ts,
        "X-Tenant-Signature": signature,
    }
    if data_residency:
        headers["X-Data-Residency"] = data_residency
    return headers


def _require_trusted_tenant_headers(
    request: Request,
    *,
    user_id: str | None,
    tenant_id: str,
    org_id: str,
    workspace_id: str,
    data_residency: str,
) -> None:
    custom_scope = (
        tenant_id != "default"
        or org_id != "default"
        or workspace_id != "default"
        or bool(data_residency)
    )
    if not custom_scope:
        return

    signature = request.headers.get("x-tenant-signature", "").strip()
    timestamp = request.headers.get("x-tenant-timestamp", "").strip()
    secret = str(settings.trusted_tenant_header_secret or "")
    if not secret or not signature or not timestamp:
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code,
            message="Untrusted tenant scope",
        )
    try:
        age_seconds = abs(int(time.time()) - int(timestamp))
    except ValueError as exc:
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code,
            message="Invalid tenant signature timestamp",
        ) from exc
    if age_seconds > max(1, int(settings.trusted_tenant_header_max_age_seconds)):
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code,
            message="Expired tenant scope signature",
        )

    payload = _tenant_signature_payload(
        user_id=user_id,
        tenant_id=tenant_id,
        org_id=org_id,
        workspace_id=workspace_id,
        data_residency=data_residency,
        timestamp=timestamp,
    )
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AppException(
            ErrorCodes.PERMISSION_DENIED.code,
            message="Invalid tenant scope signature",
        )


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
    tenant_id = str(hdr.get("tenant_id") or "default").strip() or "default"
    org_id = str(hdr.get("org_id") or "default").strip() or "default"
    workspace_id = str(hdr.get("workspace_id") or "default").strip() or "default"
    data_residency = str(hdr.get("data_residency") or "").strip()
    _require_trusted_tenant_headers(
        request,
        user_id=user_id,
        tenant_id=tenant_id,
        org_id=org_id,
        workspace_id=workspace_id,
        data_residency=data_residency,
    )
    md: dict[str, Any] = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "workspace_id": workspace_id,
    }
    if data_residency:
        md["data_residency"] = data_residency
    if user_id:
        md["user_id"] = user_id
    ensure_tenant_registered(tenant_id)
    ctx = resolve_tenant_context(user_id=user_id, metadata=md)
    try:
        from tenant.policy_manager import PolicyManager

        md = PolicyManager().apply_to_metadata(ctx, ctx.to_dict())
        return md
    except Exception as exc:
        logger.warning("tenant_policy_apply_skipped", error=str(exc))
        return ctx.to_dict()
