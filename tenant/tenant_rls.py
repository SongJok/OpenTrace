"""PostgreSQL RLS helpers for tenant/workspace and trusted worker sessions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from infra.observability.logger import get_logger

logger = get_logger(__name__)

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


def _strict_rls() -> bool:
    from infra.config.settings import settings

    return bool(settings.enterprise_tenant_rls_enabled)


async def set_session_scope(db: Any, *, tenant_id: str, workspace_id: str = "default") -> None:
    """在当前事务设置租户/工作区；启用 RLS 后设置失败必须阻断请求。"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :value, true)"),
            {"value": tenant_id or "default"},
        )
        await db.execute(
            text("SELECT set_config('app.workspace_id', :value, true)"),
            {"value": workspace_id or "default"},
        )
        await db.execute(text("SELECT set_config('app.service_role', '', true)"))
    except Exception as exc:
        if _strict_rls():
            logger.error("tenant_rls_scope_failed", error=str(exc))
            raise
        logger.warning("tenant_rls_scope_skipped", error=str(exc))


async def set_worker_session(db: Any) -> None:
    """授予后台 Worker 跨租户 claim 能力；只能在非 HTTP Worker 进程调用。"""
    try:
        await db.execute(text("SELECT set_config('app.service_role', 'worker', true)"))
    except Exception as exc:
        if _strict_rls():
            logger.error("tenant_rls_worker_role_failed", error=str(exc))
            raise
        logger.warning("tenant_rls_worker_role_skipped", error=str(exc))


async def set_session_tenant(db: Any, tenant_id: str) -> None:
    await set_session_scope(db, tenant_id=tenant_id, workspace_id="default")


async def ensure_tenant_schema() -> bool:
    """仅开发环境兼容；正式环境必须通过 Alembic。"""
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "enterprise_tenant_rls_enabled", False)):
            return False
        from infra.storage.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(text(TENANTS_TABLE_DDL))
            await db.commit()
        return True
    except Exception as exc:
        logger.debug("tenant_rls_schema_skipped", error=str(exc))
        return False


def require_tenant_persist(settings: Any) -> bool:
    env = str(getattr(settings, "app_env", "development") or "development").lower()
    if env not in ("production", "staging"):
        return False
    return bool(getattr(settings, "enterprise_tenant_rls_enabled", False))
