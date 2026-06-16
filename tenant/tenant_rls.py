"""Row-level security helpers for multi-tenant Postgres (enterprise P2)."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)

# SQL applied when `enterprise_tenant_rls_enabled` and migrations exist.
TENANTS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL DEFAULT 'standard',
    data_residency TEXT NOT NULL DEFAULT 'default',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

RLS_POLICY_DDL = """
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenants_tenant_isolation ON tenants;
CREATE POLICY tenants_tenant_isolation ON tenants
    USING (tenant_id = current_setting('app.tenant_id', true));
"""


async def set_session_tenant(db: Any, tenant_id: str) -> None:
    """Set Postgres session variable for RLS policies."""
    if not tenant_id:
        return
    try:
        from sqlalchemy import text

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
    except Exception as exc:
        logger.warning("tenant_rls_set_session_skipped", error=str(exc))


async def ensure_tenant_schema() -> bool:
    """Best-effort DDL; returns True if tenants table likely exists."""
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "enterprise_tenant_rls_enabled", False)):
            return False
        from infra.storage.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(text(TENANTS_TABLE_DDL))
            await db.commit()
        return True
    except Exception as exc:
        logger.debug("tenant_rls_schema_skipped", error=str(exc))
        return False


def require_tenant_persist(settings: Any) -> bool:
    """When RLS is on in production, disallow silent in-memory-only tenant registry."""
    env = str(getattr(settings, "app_env", "development") or "development").lower()
    if env not in ("production", "staging"):
        return False
    return bool(getattr(settings, "enterprise_tenant_rls_enabled", False))