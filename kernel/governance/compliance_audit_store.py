"""Persist compliance decisions for SOC2 audit trail (best-effort)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)

_MEMORY: list[dict[str, Any]] = []


async def record_compliance_event(
    *,
    tenant_id: str = "default",
    session_id: str = "",
    user_id: str = "",
    frameworks: list[str] | None = None,
    violations: list[str] | None = None,
    allowed: bool = True,
    payload: dict[str, Any] | None = None,
) -> str:
    event_id = str(uuid.uuid4())
    row = {
        "event_id": event_id,
        "tenant_id": tenant_id or "default",
        "session_id": session_id,
        "user_id": user_id,
        "frameworks": list(frameworks or []),
        "violations": list(violations or []),
        "allowed": allowed,
        "payload": dict(payload or {}),
    }
    _MEMORY.append(row)
    if len(_MEMORY) > 500:
        del _MEMORY[:250]
    try:
        from sqlalchemy import text

        from infra.storage.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO compliance_audit_events (
                        event_id, tenant_id, session_id, user_id,
                        frameworks, violations, allowed, payload_json
                    )
                    VALUES (
                        :eid::uuid, :tid, :sid, :uid,
                        :fw::jsonb, :viol::jsonb, :allowed, :payload::jsonb
                    )
                    """
                ),
                {
                    "eid": event_id,
                    "tid": row["tenant_id"],
                    "sid": session_id or None,
                    "uid": user_id or None,
                    "fw": json.dumps(row["frameworks"]),
                    "viol": json.dumps(row["violations"]),
                    "allowed": allowed,
                    "payload": json.dumps(row["payload"]),
                },
            )
            await db.commit()
    except Exception as exc:
        logger.debug("compliance_audit persist skipped", error=str(exc))
    return event_id


def list_recent_events(tenant_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    tid = tenant_id or "default"
    return [e for e in reversed(_MEMORY) if e.get("tenant_id") == tid][:limit]


async def list_recent_events_from_db(
    tenant_id: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Prefer Postgres audit trail; merge with in-memory buffer."""
    tid = tenant_id or "default"
    mem = list_recent_events(tid, limit=limit)
    try:
        from sqlalchemy import text

        from infra.storage.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            res = await db.execute(
                text(
                    """
                    SELECT event_id::text, tenant_id, session_id, user_id,
                           frameworks, violations, allowed, payload_json, created_at
                    FROM compliance_audit_events
                    WHERE tenant_id = :tid
                    ORDER BY created_at DESC
                    LIMIT :lim
                    """
                ),
                {"tid": tid, "lim": limit},
            )
            rows = res.mappings().all()
        if rows:
            out: list[dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "event_id": r["event_id"],
                        "tenant_id": r["tenant_id"],
                        "session_id": r["session_id"] or "",
                        "user_id": r["user_id"] or "",
                        "frameworks": r["frameworks"] if isinstance(r["frameworks"], list) else [],
                        "violations": r["violations"] if isinstance(r["violations"], list) else [],
                        "allowed": bool(r["allowed"]),
                        "payload": r["payload_json"] if isinstance(r["payload_json"], dict) else {},
                    }
                )
            return out
    except Exception as exc:
        logger.debug("compliance_audit db read skipped", error=str(exc))
    return mem