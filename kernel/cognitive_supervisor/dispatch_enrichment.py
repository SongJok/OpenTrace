"""
Post-prepare runtime enrichment — owned by CognitiveSupervisor, not RuntimeTurnDispatcher.

Goal execution projection, runtime grounding, cognitive runtime state, context fabric dispatch phase.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def apply_dispatch_enrichment(request: Any, prepared: Any) -> None:
    """Mutate request.metadata and ctx.metadata after prepare_run, before runtime dispatch."""
    from kernel.cognition.runtime_grounding import project_from_context
    from kernel.goal.goal_projection import project_goal_graph_to_execution_hints
    from kernel.runtime.cognitive_state.bus import bind_state_to_context, hydrate_state_from_store
    from kernel.runtime.cognitive_state.store import get_or_create_runtime_state

    ctx = prepared.ctx
    if ctx is None:
        return
    md = ctx.metadata or {}
    gg = prepared.goal_graph_dict or md.get("goal_graph") or {}
    root = str(gg.get("root_goal_id", "") or getattr(ctx, "request_id", ""))
    if gg:
        hints = project_goal_graph_to_execution_hints(gg)
        md["goal_execution_projection"] = hints
        request.metadata = dict(request.metadata or {})
        request.metadata["goal_execution_projection"] = hints

    grounding = project_from_context(ctx)
    try:
        from kernel.governance.adaptive_risk_engine import AdaptiveRiskEngine

        lock = (request.metadata or {}).get("intent_lock") or {}
        budget = lock.get("cognitive_budget") or {}
        sub_count = max(0, len((gg.get("goals") or [])) - 1) if isinstance(gg, dict) else 0
        ar = AdaptiveRiskEngine().score_turn(
            hallucination_risk=0.0,
            replanned=bool(md.get("refine_replan")),
            evidence_count=0,
            sub_goal_count=sub_count,
        )
        if int(budget.get("max_replans", 3) or 3) <= 1 and sub_count > 2:
            ar.score = min(1.0, ar.score + 0.08)
            ar.factors.append("tight_replan_budget_multi_goal")
        md["adaptive_risk"] = {
            "level": ar.level,
            "score": ar.score,
            "factors": list(ar.factors),
        }
        grounding.risk.level = ar.level
        grounding.risk.score = ar.score
        grounding.risk.factors = list(ar.factors)
    except Exception as exc:
        from infra.observability.runtime_degraded import record_degradation_in_context

        record_degradation_in_context(
            ctx, subsystem="adaptive_risk", detail="dispatch_enrichment", exc=exc
        )
        logger.debug("adaptive_risk enrichment skipped", exc_info=True)

    md["runtime_grounding"] = grounding.to_dict()
    request.metadata = dict(request.metadata or {})
    request.metadata["runtime_grounding"] = md["runtime_grounding"]
    request.metadata["adaptive_risk"] = md.get("adaptive_risk")

    rs = get_or_create_runtime_state(
        str(getattr(ctx, "request_id", "") or ""),
        str(getattr(ctx, "session_id", "") or request.session_id or ""),
        goal_id=root,
    )
    rs.world_state_snapshot = dict(md.get("goal_world_projection") or {})
    bind_state_to_context(ctx, rs)
    try:
        import asyncio

        asyncio.get_running_loop().create_task(hydrate_state_from_store(ctx))
    except RuntimeError:
        pass

    ctx.metadata = md
    request.metadata.setdefault("cognitive_runtime_state", md.get("cognitive_runtime_state"))

    try:
        from kernel.context_fabric import get_context_fabric

        graph_dict = get_context_fabric().evolve_runtime(
            str(getattr(ctx, "session_id", "") or request.session_id or ""),
            goal_id=root,
            runtime_phase="dispatch",
        )
        md["fabric_graph_live"] = graph_dict
        ctx.metadata = md
    except Exception as exc:
        from infra.observability.runtime_degraded import record_degradation_in_context

        record_degradation_in_context(
            ctx, subsystem="context_fabric", detail="dispatch_evolve", exc=exc
        )
        logger.debug("context_fabric dispatch evolve skipped", exc_info=True)

    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_autonomous_goal_discovery_enabled", True)):
            from kernel.goal.autonomous_goal_discovery import (
                attach_proposals_to_metadata,
                propose_goals_from_signals,
            )

            gs = (request.metadata or {}).get("goal_supervisor") or {}
            md_merged = {**(request.metadata or {}), **md}
            cg = md_merged.get("claim_graph") or {}
            rei = md_merged.get("rag_evidence_intelligence") or {}
            if isinstance(rei, dict) and not cg:
                cg = rei.get("claim_graph") or rei
            proposals = propose_goals_from_signals(
                query=str(getattr(request, "query", "") or ""),
                claim_graph=cg if isinstance(cg, dict) else None,
                anomaly_hints=list(gs.get("domains") or []),
                root_id=root or "goal",
            )
            request.metadata = dict(request.metadata or {})
            attach_proposals_to_metadata(request.metadata, proposals)
            md["autonomous_goal_proposals"] = request.metadata.get("autonomous_goal_proposals")
            from kernel.goal.autonomous_goal_discovery import maybe_mount_proposals_on_goal_graph

            mount = maybe_mount_proposals_on_goal_graph(request.metadata)
            if mount.get("mounted"):
                md["goal_graph"] = request.metadata.get("goal_graph")
                md["autonomous_goal_mounted"] = mount.get("mounted")
            ctx.metadata = md
    except Exception as exc:
        from infra.observability.runtime_degraded import record_degradation_in_context

        record_degradation_in_context(
            ctx, subsystem="autonomous_goal_discovery", detail="dispatch", exc=exc
        )