from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import AuditLog, ReasoningTrace, SystemSetting, TraceLog


async def _get_retention_days(default_days: int = 30) -> int:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(SystemSetting).where(SystemSetting.key == "trace_retention_days"))
        s = r.scalar_one_or_none()
        if s is None:
            return default_days
        try:
            return max(1, int(s.value))
        except Exception:
            return default_days


async def cleanup_retention() -> dict[str, int]:
    days = await _get_retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with AsyncSessionLocal() as db:
        r1 = await db.execute(delete(ReasoningTrace).where(ReasoningTrace.created_at < cutoff))
        r2 = await db.execute(delete(TraceLog).where(TraceLog.created_at < cutoff))
        r3 = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        await db.commit()

        return {
            "trace_retention_days": days,
            "reasoning_traces_deleted": int(r1.rowcount or 0),
            "trace_logs_deleted": int(r2.rowcount or 0),
            "audit_logs_deleted": int(r3.rowcount or 0),
        }


if __name__ == "__main__":
    out = asyncio.run(cleanup_retention())
    print(out)
