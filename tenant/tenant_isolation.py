"""Enterprise tenant isolation — RLS session vars and query filters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tenant.tenant_context import TenantContext


async def set_session_tenant_context(db: AsyncSession, ctx: TenantContext) -> None:
    """Set Postgres session variables for RLS policies (when enabled on tables)."""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": ctx.tenant_id or "default"},
        )
        await db.execute(
            text("SELECT set_config('app.org_id', :oid, true)"),
            {"oid": ctx.org_id or "default"},
        )
        await db.execute(
            text("SELECT set_config('app.workspace_id', :wid, true)"),
            {"wid": ctx.workspace_id or "default"},
        )
    except Exception:
        pass


def tenant_filter_clause(
    *,
    table_alias: str = "",
    tenant_column: str = "tenant_id",
) -> str:
    """SQL fragment for application-level tenant scoping."""
    prefix = f"{table_alias}." if table_alias else ""
    return f"{prefix}{tenant_column} = current_setting('app.tenant_id', true)"


def scope_metadata(metadata: dict[str, Any], ctx: TenantContext) -> dict[str, Any]:
    md = dict(metadata or {})
    md.setdefault("tenant_id", ctx.tenant_id)
    md.setdefault("org_id", ctx.org_id)
    md.setdefault("workspace_id", ctx.workspace_id)
    md["isolation_key"] = ctx.isolation_key()
    return md