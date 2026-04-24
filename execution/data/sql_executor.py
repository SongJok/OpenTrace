from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


class SQLExecutor:
    async def run(self, db: AsyncSession, sql: str) -> list[dict[str, Any]]:
        result = await db.execute(text(sql))
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def run_on_dsn(self, dsn: str, sql: str) -> list[dict[str, Any]]:
        engine = create_async_engine(dsn, pool_pre_ping=True, future=True)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql))
                rows = result.mappings().all()
                return [dict(r) for r in rows]
        finally:
            await engine.dispose()
