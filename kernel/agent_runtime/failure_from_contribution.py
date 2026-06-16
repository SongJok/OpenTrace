"""Record Capability Intelligence failures from RuntimeContribution risk signals."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from kernel.agent_runtime.runtime_contribution import RuntimeContribution, RiskSignal
from kernel.capability_intelligence.failure_memory import FailureRecord, failure_memory

logger = get_logger(__name__)

_RISK_TO_FAILURE: dict[str, str] = {
    "capability_execution_failed": "exception",
    "low_confidence_answer": "low_critic",
    "low_confidence_circuit_breaker": "low_confidence_circuit_breaker",
    "policy_tag": "user_dissatisfaction",
    "timeout": "timeout",
    "hallucination": "hallucination",
    "contradiction": "contradiction",
    "empty_result": "empty_result",
}


def _failure_type_from_risk(risk: RiskSignal) -> str:
    if risk.code in _RISK_TO_FAILURE:
        return _RISK_TO_FAILURE[risk.code]
    msg = (risk.message or "").lower()
    if "timeout" in msg:
        return "timeout"
    if "hallucin" in msg:
        return "hallucination"
    if "contradict" in msg:
        return "contradiction"
    if "empty" in msg:
        return "empty_result"
    if risk.severity >= 0.65:
        return "exception"
    return "low_critic"


def record_risks_from_contribution(
    contribution: RuntimeContribution,
    *,
    query_preview: str = "",
) -> int:
    """Write risk signals into global failure_memory. Returns count recorded."""
    count = 0
    cap = contribution.capability_type or contribution.agent_type or "unknown"
    for risk in contribution.risks or []:
        if risk.severity < 0.35 and risk.code != "capability_execution_failed":
            continue
        failure_memory.record(
            FailureRecord(
                capability_type=risk.source_capability or cap,
                failure_type=_failure_type_from_risk(risk),
                query_pattern=(query_preview or contribution.content or "")[:100],
                context_snapshot=f"{risk.code}:{risk.message}"[:200],
                latency_ms=int(contribution.latency_ms or 0),
            )
        )
        count += 1
    if contribution.status not in ("success", "ok", "done") and not contribution.risks:
        failure_memory.record_from_result(
            cap,
            query_preview or contribution.content or "",
            success=False,
            error_msg=str(contribution.error or contribution.status),
            latency_ms=int(contribution.latency_ms or 0),
            critic_score=contribution.confidence,
        )
        count += 1
    return count


def record_turn_failure_signals(
    agent_results: list[Any],
    *,
    query_preview: str = "",
    root_goal_id: str = "",
    goal_description: str = "",
    trace_id: str = "",
    session_id: str = "",
    merged: RuntimeContribution | None = None,
) -> dict[str, Any]:
    """Merge contributions if needed, then record all risks + failed statuses."""
    from kernel.runtime.evidence_runtime import merge_turn_evidence

    total = 0
    if merged is None:
        merged, _ = merge_turn_evidence(
            agent_results,
            root_goal_id=root_goal_id,
            goal_description=goal_description,
            trace_id=trace_id,
            session_id=session_id,
        )
    total += record_risks_from_contribution(merged, query_preview=query_preview)
    return {"failure_memory_records": total, "risk_count": len(merged.risks or [])}