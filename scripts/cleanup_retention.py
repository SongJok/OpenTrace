from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from infra.config.settings import settings
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    ChatSession,
    LegalHold,
    ReasoningTrace,
    RevokedToken,
    SystemSetting,
    TraceLog,
)


async def _get_retention_days(default_days: int | None = None) -> int:
    fallback = int(default_days or settings.enterprise_default_retention_days)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == "trace_retention_days")
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            return fallback
        try:
            return max(1, int(stored.value))
        except (TypeError, ValueError):
            return fallback


async def cleanup_retention() -> dict[str, int]:
    days = await _get_retention_days()
    cutoff = datetime.now(UTC) - timedelta(days=days)

    async with AsyncSessionLocal() as db:
        held_tenants = select(LegalHold.tenant_id).where(
            LegalHold.status == "active",
            LegalHold.expires_at.is_(None) | (LegalHold.expires_at > datetime.now(UTC)),
        )
        held_sessions = select(ChatSession.id).where(ChatSession.tenant_id.in_(held_tenants))
        reasoning = await db.execute(
            delete(ReasoningTrace).where(
                ReasoningTrace.created_at < cutoff,
                ReasoningTrace.session_id.not_in(held_sessions),
            )
        )
        traces = await db.execute(
            delete(TraceLog).where(
                TraceLog.created_at < cutoff,
                TraceLog.session_id.not_in(held_sessions),
            )
        )
        revoked = await db.execute(
            delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(UTC))
        )
        # AuditLog 是合规证据，不再跟随短期 Trace 保留策略删除。
        await db.commit()
        return {
            "trace_retention_days": days,
            "reasoning_traces_deleted": int(reasoning.rowcount or 0),
            "trace_logs_deleted": int(traces.rowcount or 0),
            "audit_logs_deleted": 0,
            "revoked_tokens_deleted": int(revoked.rowcount or 0),
        }


if __name__ == "__main__":
    print(asyncio.run(cleanup_retention()))
