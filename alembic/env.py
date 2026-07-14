"""
Alembic async environment — fixed version.
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import infra.storage.models  # noqa: F401 — registers ORM models
from alembic import context

# Import all models so their metadata is registered
from infra.config.settings import settings
from infra.storage.database import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# The application runs inside Docker where ``postgres`` is resolvable, while
# developers commonly invoke Alembic on the host where the published port is
# reachable as ``localhost``.  Keep application settings unchanged and allow
# an explicit one-command override for host migrations.
db_url = os.getenv("ALEMBIC_DATABASE_URL") or settings.database_url or config.get_main_option("sqlalchemy.url")
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
target_metadata = Base.metadata


class _OfflineInspector:
    """Schema-free inspector for idempotent migrations during SQL rendering."""

    def get_table_names(self):
        return []

    def get_indexes(self, _table):
        return []

    def get_columns(self, _table):
        return []


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    original_inspect = sa.inspect
    sa.inspect = lambda _bind: _OfflineInspector()  # type: ignore[assignment]
    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        sa.inspect = original_inspect  # type: ignore[assignment]


def _run_migrations(sync_conn) -> None:
    context.configure(
        connection=sync_conn,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
