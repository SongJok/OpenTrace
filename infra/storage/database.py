"""
AsyncPG / SQLAlchemy async engine + session factory.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
engine = create_async_engine(
    settings.database_url,
    pool_size=settings.pool_size,
    max_overflow=settings.max_overflow,
    pool_timeout=settings.pool_timeout,
    pool_recycle=settings.pool_recycle,
    echo=settings.debug,
    future=True,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Declarative base shared by all models
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------
@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Context-manager style — use in non-FastAPI code."""
    t0 = time.monotonic()
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
            logger.debug("DB session commit", latency_ms=int((time.monotonic() - t0) * 1000))
        except Exception as exc:
            await session.rollback()
            logger.warning(
                "DB session rollback",
                error=str(exc),
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            raise


async def db_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends() helper."""
    async with get_db_session() as session:
        yield session


async def init_db() -> None:
    """Create all tables (dev/test only — use Alembic in production)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_chat_sessions_columns(conn)
        await _ensure_conversation_states_columns(conn)
        await _ensure_enterprise_tenant_tables(conn)
    logger.info("Database tables initialised")


async def ensure_runtime_schema() -> None:
    """Best-effort runtime schema guard for local/dev databases.

    SQLAlchemy create_all() does not alter existing tables, so older local
    databases can miss columns added to ORM models by later migrations. The
    chat UI reads chat_sessions immediately after login; missing columns there
    make the app unusable before a user can run manual migrations.
    """
    try:
        async with engine.begin() as conn:
            if settings.app_env in {"staging", "production"}:
                await _verify_runtime_schema(conn)
                return
            await _ensure_chat_sessions_columns(conn)
            await _ensure_conversation_states_columns(conn)
            await _ensure_enterprise_tenant_tables(conn)
            await _ensure_documents_tenant_columns(conn)
    except Exception as exc:  # noqa: BLE001
        if settings.app_env in {"staging", "production"}:
            logger.error("Runtime schema readiness failed", error=str(exc))
            raise
        logger.warning("Runtime schema guard failed", error=str(exc))


async def _verify_runtime_schema(conn) -> None:
    """staging/production 只读校验 schema；迁移缺失时让启动失败。"""
    required_columns = {
        "chat_sessions": {
            "display_title",
            "turn_count",
            "last_decision_type",
            "tags",
            "pinned",
            "archived_at",
            "tenant_id",
            "org_id",
            "workspace_id",
        },
        "conversation_states": {
            "active_mode",
            "active_data_source_id",
            "active_document_ids",
            "active_attachment_ids",
            "pending_clarification",
            "state_version",
            "state_extension",
        },
        "documents": {"tenant_id", "workspace_id"},
    }
    missing: list[str] = []
    for table, columns in required_columns.items():
        rows = await conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table
                """
            ),
            {"table": table},
        )
        present = {str(row[0]) for row in rows}
        for column in sorted(columns - present):
            missing.append(f"{table}.{column}")

    required_tables = {
        "tenants",
        "tenant_workspaces",
        "compliance_audit_events",
        "knowledge_sources",
        "knowledge_source_versions",
        "knowledge_pages",
        "knowledge_claims",
        "knowledge_relations",
        "knowledge_compilation_jobs",
        "knowledge_lint_issues",
        "knowledge_feedback",
        "knowledge_rules",
        "knowledge_observations",
        "knowledge_merge_cases",
        "responses",
        "response_items",
        "response_events",
        "user_custom_instructions",
    }
    table_rows = await conn.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
    )
    present_tables = {str(row[0]) for row in table_rows}
    for table in sorted(required_tables - present_tables):
        missing.append(table)

    if missing:
        raise RuntimeError(
            "runtime schema is not migration-ready; missing: " + ", ".join(missing)
        )


async def _ensure_chat_sessions_columns(conn) -> None:
    """Idempotently add ChatSession columns required by current ORM queries."""
    statements = [
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS display_title VARCHAR(255)",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS turn_count INTEGER DEFAULT 0",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS last_decision_type VARCHAR(50)",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS tags VARCHAR[] NOT NULL DEFAULT ARRAY[]::VARCHAR[]",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP WITH TIME ZONE",
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_archived_at "
        "ON public.chat_sessions (archived_at)",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS org_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_tenant "
        "ON public.chat_sessions (tenant_id, org_id, workspace_id)",
    ]
    for stmt in statements:
        await conn.execute(text(stmt))


async def _ensure_conversation_states_columns(conn) -> None:
    """Idempotently add ConversationState columns required by current ORM queries."""
    statements = [
        "ALTER TABLE IF EXISTS public.conversation_states "
        "ADD COLUMN IF NOT EXISTS active_mode VARCHAR(64)",
        "ALTER TABLE IF EXISTS public.conversation_states "
        "ADD COLUMN IF NOT EXISTS active_data_source_id VARCHAR(36)",
        "ALTER TABLE IF EXISTS public.conversation_states "
        "ADD COLUMN IF NOT EXISTS active_document_ids JSON NOT NULL DEFAULT '[]'::json",
        "ALTER TABLE IF EXISTS public.conversation_states "
        "ADD COLUMN IF NOT EXISTS active_attachment_ids JSON NOT NULL DEFAULT '[]'::json",
        "ALTER TABLE IF EXISTS public.conversation_states "
        "ADD COLUMN IF NOT EXISTS pending_clarification JSON",
        "ALTER TABLE IF EXISTS public.conversation_states "
        "ADD COLUMN IF NOT EXISTS state_version INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE IF EXISTS public.conversation_states "
        "ADD COLUMN IF NOT EXISTS state_extension JSON NOT NULL DEFAULT '{}'::json",
    ]
    for stmt in statements:
        await conn.execute(text(stmt))


async def _ensure_documents_tenant_columns(conn) -> None:
    """Idempotently add Document tenant/workspace columns for RAG scope."""
    statements = [
        "ALTER TABLE IF EXISTS public.documents "
        "ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE IF EXISTS public.documents "
        "ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON public.documents (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_documents_tenant_workspace "
        "ON public.documents (tenant_id, workspace_id)",
    ]
    for stmt in statements:
        await conn.execute(text(stmt))


async def _ensure_enterprise_tenant_tables(conn) -> None:
    """Multi-tenant skeleton tables for tenant_store upsert."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS public.tenants (
            tenant_id VARCHAR(128) PRIMARY KEY,
            name VARCHAR(255) NOT NULL DEFAULT '',
            tier VARCHAR(64) NOT NULL DEFAULT 'standard',
            data_residency VARCHAR(64) NOT NULL DEFAULT 'global',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS public.tenant_workspaces (
            workspace_id VARCHAR(128) NOT NULL,
            tenant_id VARCHAR(128) NOT NULL REFERENCES public.tenants(tenant_id) ON DELETE CASCADE,
            org_id VARCHAR(128) NOT NULL DEFAULT 'default',
            name VARCHAR(255) NOT NULL DEFAULT '',
            policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (tenant_id, workspace_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS public.compliance_audit_events (
            event_id UUID PRIMARY KEY,
            tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
            session_id VARCHAR(128),
            user_id VARCHAR(128),
            frameworks JSONB NOT NULL DEFAULT '[]'::jsonb,
            violations JSONB NOT NULL DEFAULT '[]'::jsonb,
            allowed BOOLEAN NOT NULL DEFAULT TRUE,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_compliance_audit_tenant "
        "ON public.compliance_audit_events (tenant_id, created_at DESC)",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS org_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE IF EXISTS public.chat_sessions "
        "ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_tenant "
        "ON public.chat_sessions (tenant_id, org_id, workspace_id)",
    ]
    for stmt in statements:
        await conn.execute(text(stmt.strip()))


async def close_db() -> None:
    await engine.dispose()
    logger.info("Database engine disposed")
