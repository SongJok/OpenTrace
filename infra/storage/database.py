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
            await _ensure_chat_sessions_columns(conn)
            await _ensure_conversation_states_columns(conn)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Runtime schema guard failed", error=str(exc))


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


async def close_db() -> None:
    await engine.dispose()
    logger.info("Database engine disposed")
