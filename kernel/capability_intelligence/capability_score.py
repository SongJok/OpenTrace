"""Capability score — success, latency, feedback composite for dispatch ranking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from kernel.capability_intelligence.feedback import CapabilityFeedbackLoop
from kernel.capability_intelligence.profiler import CapabilityProfiler


@dataclass
class CapabilityScore:
    capability_type: str
    score: float = 0.0
    success_rate: float = 0.0
    avg_latency_ms: int = 0
    evidence_quality: float = 0.0
    sample_count: int = 0
    tier: str = "active"  # active | degraded | canary

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_type": self.capability_type,
            "score": round(self.score, 4),
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": self.avg_latency_ms,
            "evidence_quality": round(self.evidence_quality, 4),
            "sample_count": self.sample_count,
            "tier": self.tier,
        }


def _latency_penalty(latency_ms: int, baseline_ms: int = 3000) -> float:
    if latency_ms <= 0:
        return 0.0
    return min(0.35, (latency_ms / max(baseline_ms, 1)) * 0.15)


def compute_capability_score(
    capability_type: str,
    *,
    profiler: CapabilityProfiler | None = None,
    feedback: CapabilityFeedbackLoop | None = None,
) -> CapabilityScore:
    profiler = profiler or CapabilityProfiler()
    feedback = feedback or CapabilityFeedbackLoop(profiler)
    stats = feedback.recent_stats(capability_type, n=20)
    success_rate = float(stats.get("success_rate", 0.5) or 0.5)
    avg_lat = int(stats.get("avg_latency_ms", 0) or 0)
    eq = float(stats.get("avg_evidence_quality", 0.5) or 0.5)
    n = int(stats.get("count", 0) or 0)
    raw = 0.45 * success_rate + 0.35 * eq + 0.2 * (1.0 - _latency_penalty(avg_lat))
    raw = max(0.0, min(1.0, raw))
    tier = "active"
    if n >= 5 and success_rate < 0.35:
        tier = "degraded"
    elif n < 3:
        tier = "canary"
    return CapabilityScore(
        capability_type=capability_type,
        score=raw,
        success_rate=success_rate,
        avg_latency_ms=avg_lat,
        evidence_quality=eq,
        sample_count=n,
        tier=tier,
    )


def rank_capabilities_by_score(
    capability_types: list[str],
    *,
    intent_category: str = "general",
) -> list[dict[str, Any]]:
    """Merge control-plane rank with capability score."""
    from kernel.capability_runtime.capability_control_plane import (
        get_capability_descriptor,
        rank_capabilities_for_intent as control_plane_rank,
    )
    from kernel.capability_runtime.topology import dependents_of
    from kernel.runtime.capability import capability_registry

    base = control_plane_rank(
        capability_types,
        allowed=None,
        max_items=len(capability_types) or 8,
    )
    if not base:
        return []
    enriched: list[dict[str, Any]] = []
    for row in base:
        ctype = str(row.get("capability_type", "") or "")
        score = float(row.get("score", 0.0) or 0.0)
        if intent_category == "data_query" and ctype == "data_query":
            score += 0.5
        if dependents_of(ctype):
            score += 0.05
        desc = get_capability_descriptor(ctype)
        meta = desc.to_dict() if desc else capability_registry.runtime_metadata(ctype)
        enriched.append(
            {
                "capability_type": ctype,
                "score": round(score, 4),
                "metadata": meta,
                "owner_runtime": row.get("owner_runtime") or (desc.owner_runtime if desc else ""),
            }
        )
    base = enriched
    out: list[dict[str, Any]] = []
    for row in base:
        ctype = str(row.get("capability_type", "") or "")
        cs = compute_capability_score(ctype)
        merged = float(row.get("score", 0.0) or 0.0) + cs.score * 0.4
        if cs.tier == "degraded":
            merged *= 0.5
        out.append(
            {
                **row,
                "score": round(merged, 4),
                "capability_score": cs.to_dict(),
            }
        )
    out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return out


def record_capability_outcome(
    capability_type: str,
    *,
    success: bool,
    latency_ms: int,
    evidence_quality: float,
    query_preview: str = "",
) -> CapabilityScore:
    from kernel.capability_intelligence.profile import ExecutionRecord

    profiler = CapabilityProfiler()
    loop = CapabilityFeedbackLoop(profiler)
    loop.record(
        ExecutionRecord(
            capability_type=capability_type,
            query_preview=(query_preview or "")[:80],
            success=bool(success),
            latency_ms=int(latency_ms or 0),
            evidence_quality=max(0.0, min(1.0, evidence_quality)),
            timestamp=time.time(),
        )
    )
    return compute_capability_score(capability_type, profiler=profiler, feedback=loop)