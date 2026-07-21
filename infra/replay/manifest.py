from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import ReasoningTrace, TraceLog


@dataclass
class ReplayStep:
    phase: str
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    latency_ms: int | None = None
    model: str | None = None
    created_at: str | None = None


@dataclass
class ReplayManifest:
    version: str
    trace_id: str
    session_id: str | None
    query: str
    response: str
    decision_type: str | None
    total_latency_ms: int | None
    created_at: str | None
    steps: list[ReplayStep] = field(default_factory=list)


async def build_replay_manifest(db: AsyncSession, trace_id: str) -> ReplayManifest:
    r = await db.execute(select(TraceLog).where(TraceLog.id == trace_id))
    trace = r.scalar_one_or_none()
    if trace is None:
        raise ValueError("trace not found")

    rr = await db.execute(
        select(ReasoningTrace)
        .where(ReasoningTrace.session_id == trace.session_id)
        .order_by(ReasoningTrace.created_at.asc())
    )
    rows = rr.scalars().all()

    steps: list[ReplayStep] = []
    for x in rows:
        meta = json.loads(x.phase_metadata or "{}") if x.phase_metadata else {}
        steps.append(
            ReplayStep(
                phase=x.phase,
                input=meta.get("input", {}),
                output={"content": x.content, "score": x.score, **meta.get("output", {})},
                latency_ms=meta.get("latency_ms"),
                model=meta.get("model"),
                created_at=x.created_at.isoformat() if isinstance(x.created_at, datetime) else None,
            )
        )

    return ReplayManifest(
        version="replay-manifest/v1",
        trace_id=trace.id,
        session_id=trace.session_id,
        query=trace.query,
        response=trace.response or "",
        decision_type=trace.decision_type,
        total_latency_ms=trace.latency_ms,
        created_at=trace.created_at.isoformat() if trace.created_at else None,
        steps=steps,
    )


def manifest_to_dict(m: ReplayManifest) -> dict[str, Any]:
    return asdict(m)
