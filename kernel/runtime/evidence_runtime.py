"""Evidence Runtime — unified read path for turn-level evidence (no raw AgentResult)."""

from __future__ import annotations

from typing import Any

from kernel.agent_runtime.runtime_contribution import (
    RuntimeContribution,
    merge_runtime_contributions,
    runtime_contribution_from_agent_result,
)
from kernel.agent_runtime.unified_evidence import UnifiedEvidence, normalize_evidence_list


def contributions_from_agent_results(
    agent_results: list[Any],
    *,
    root_goal_id: str = "",
    goal_description: str = "",
    trace_id: str = "",
    session_id: str = "",
) -> list[RuntimeContribution]:
    out: list[RuntimeContribution] = []
    for r in agent_results or []:
        out.append(
            runtime_contribution_from_agent_result(
                r,
                goal_id=root_goal_id,
                goal_description=goal_description,
                trace_id=trace_id,
                session_id=session_id,
            )
        )
    return out


def merge_turn_evidence(
    agent_results: list[Any],
    *,
    root_goal_id: str = "",
    goal_description: str = "",
    trace_id: str = "",
    session_id: str = "",
) -> tuple[RuntimeContribution, list[UnifiedEvidence]]:
    contribs = contributions_from_agent_results(
        agent_results,
        root_goal_id=root_goal_id,
        goal_description=goal_description,
        trace_id=trace_id,
        session_id=session_id,
    )
    merged = merge_runtime_contributions(contribs, root_goal_id=root_goal_id)
    evidence = normalize_evidence_list(
        merged.evidence,
        goal_id=root_goal_id,
        trace_id=trace_id,
    )
    return merged, evidence


def enrich_evidence_with_graph(
    evidence: list[UnifiedEvidence],
    *,
    query: str = "",
) -> dict[str, Any]:
    """Optional evidence graph intelligence (contradiction / synthesis metadata)."""
    try:
        from services.evidence_graph.engine import (
            build_evidence_graph_from_items,
            detect_contradictions,
            rank_evidence,
            synthesize_evidence_summary,
        )

        items = [e.model_dump(mode="json") for e in evidence]
        ranked = rank_evidence(items)
        graph = build_evidence_graph_from_items(ranked)
        return {
            "evidence_graph": graph.to_dict(),
            "contradictions": detect_contradictions(ranked),
            "synthesis_preview": synthesize_evidence_summary(graph)[:1500],
            "query": (query or "")[:200],
        }
    except Exception:
        return {"evidence_graph": "skipped"}


def apply_turn_contributions_to_context(
    ctx: Any,
    agent_results: list[Any],
    *,
    root_goal_id: str = "",
    goal_description: str = "",
    trace_id: str = "",
) -> RuntimeContribution:
    """Single entry: merge contributions + cognitive state graph on ctx."""
    sid = str(getattr(ctx, "session_id", "") or "")
    merged, _evidence = merge_turn_evidence(
        agent_results,
        root_goal_id=root_goal_id,
        goal_description=goal_description,
        trace_id=trace_id,
        session_id=sid,
    )
    md = dict(getattr(ctx, "metadata", None) or {})
    md.update(merged.to_metadata_dict())
    md["runtime_contribution_turn"] = merged.model_dump(mode="json")
    ctx.metadata = md

    from kernel.runtime.cognitive_state.bus import apply_runtime_contribution_to_bus

    apply_runtime_contribution_to_bus(ctx, merged)
    return merged