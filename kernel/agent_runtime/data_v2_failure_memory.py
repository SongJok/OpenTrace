"""Record DataAgent V2 circuit-breaker events into global failure_memory."""

from __future__ import annotations

from typing import Any

from kernel.capability_intelligence.failure_memory import FailureRecord, failure_memory

DATA_QUERY_CAPABILITY = "data_query"
CIRCUIT_BREAKER_FAILURE_TYPE = "low_confidence_circuit_breaker"


def record_data_v2_circuit_breaker(
    *,
    query: str,
    confidence: float,
    threshold: float,
    detail: str = "",
    data_source_id: str = "",
    trace_id: str = "",
    latency_ms: int = 0,
    resolution: str = "v1_fallback_pending",
) -> str:
    """Persist V2 low-confidence breaker for Capability Intelligence / risk engine."""
    ctx = (
        f"threshold={threshold:.2f} conf={confidence:.2f} "
        f"ds={data_source_id or 'n/a'} trace={trace_id or 'n/a'} "
        f"{detail[:120]}"
    ).strip()
    failure_memory.record(
        FailureRecord(
            capability_type=DATA_QUERY_CAPABILITY,
            failure_type=CIRCUIT_BREAKER_FAILURE_TYPE,
            query_pattern=(query or "")[:100],
            context_snapshot=ctx[:200],
            resolution=resolution[:200],
            latency_ms=int(latency_ms or 0),
        )
    )
    recs = failure_memory.get_recent_failures(DATA_QUERY_CAPABILITY, window_seconds=60)
    return recs[-1].record_id if recs else ""


def record_data_v2_circuit_breaker_from_exception(
    exc: Any,
    *,
    task: Any,
    resolution: str = "v1_fallback",
) -> str:
    """Convenience when handling LowConfidenceError in DataAgent wrapper."""
    from agents.data_agent_v2.types import LowConfidenceError

    if not isinstance(exc, LowConfidenceError):
        return ""
    params = getattr(task, "params", None) or {}
    return record_data_v2_circuit_breaker(
        query=str(getattr(task, "query", "") or ""),
        confidence=float(exc.confidence),
        threshold=float(exc.threshold),
        detail=str(exc.detail or ""),
        data_source_id=str(params.get("data_source_id") or ""),
        trace_id=str(params.get("trace_id") or params.get("request_id") or ""),
        resolution=resolution,
    )