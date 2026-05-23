from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def _make_json_safe(val: Any) -> Any:
    """Convert database-native types to JSON-serializable equivalents."""
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return val


class SQLExecutor:
    async def run(self, db: AsyncSession, sql: str) -> list[dict[str, Any]]:
        result = await db.execute(text(sql))
        rows = result.mappings().all()
        return [{k: _make_json_safe(v) for k, v in dict(r).items()} for r in rows]

    async def run_on_dsn(self, dsn: str, sql: str) -> list[dict[str, Any]]:
        engine = create_async_engine(dsn, pool_pre_ping=True, future=True)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql))
                rows = result.mappings().all()
                return [{k: _make_json_safe(v) for k, v in dict(r).items()} for r in rows]
        finally:
            await engine.dispose()
