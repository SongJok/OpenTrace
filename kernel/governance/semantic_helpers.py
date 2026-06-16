"""Extract P0/P1 signals from turn metadata for semantic health pipeline."""

from __future__ import annotations

from typing import Any


def extract_semantic_turn_signals(
    request: Any,
    ctx: Any | None,
    result: Any | None = None,
) -> dict[str, Any]:
    """Pull reflection, claim, coverage, goal_supervisor fields from metadata."""
    rmd = dict(getattr(request, "metadata", None) or {})
    cmd = dict(getattr(ctx, "metadata", None) or {}) if ctx else {}
    if result is not None:
        rmd2 = getattr(result, "metadata", None) or {}
        if isinstance(rmd2, dict):
            rmd = {**rmd, **rmd2}
    merged = {**rmd, **cmd}

    ci = merged.get("cognitive_iteration") or {}
    reflection_round = int(
        merged.get("reflection_round") or ci.get("reflection_round") or 0
    )

    claim_conflicts = 0
    for key in ("rag_evidence_intelligence", "claim_graph", "claim_pipeline"):
        block = merged.get(key)
        if isinstance(block, dict):
            claim_conflicts = max(
                claim_conflicts,
                int(block.get("conflicting_claims", 0) or 0),
            )

    coverage_score: float | None = None
    wc = merged.get("web_coverage")
    if isinstance(wc, dict) and wc.get("coverage_score") is not None:
        coverage_score = float(wc.get("coverage_score"))

    gs = merged.get("goal_supervisor") or {}
    goal_supervisor_split = bool(gs.get("split_from_root"))

    return {
        "reflection_round": reflection_round,
        "claim_conflicts": claim_conflicts,
        "coverage_score": coverage_score,
        "goal_supervisor_split": goal_supervisor_split,
    }


def record_kernel_turn_health(
    *,
    request: Any,
    response: Any | None = None,
    ctx: Any | None = None,
    route: str = "kernel_finalize",
) -> dict[str, Any]:
    """Semantic pipeline for non-executive finalize paths (KernelResponse)."""
    from kernel.governance.semantic_metrics_pipeline import get_semantic_metrics_pipeline

    session_id = str(getattr(request, "session_id", "") or "")
    md = dict(getattr(request, "metadata", None) or {})
    if response is not None:
        rmd = getattr(response, "metadata", None) or {}
        if isinstance(rmd, dict):
            md = {**md, **rmd}

    passed = True
    fusion_conf = 0.75
    hall = 0.0
    if response is not None:
        passed = bool(getattr(response, "passed_validation", True))
        fusion_conf = float(getattr(response, "validation_score", 0.75) or 0.75)
        hall = float(getattr(response, "hallucination_risk", 0.0) or 0.0)

    gkw: dict[str, Any] = {}
    try:
        from kernel.cognitive_supervisor.run_outcomes import governance_kwargs_from_ctx

        gkw = governance_kwargs_from_ctx(ctx, request)
    except Exception:
        gg = md.get("goal_graph") or {}
        goals = gg.get("goals") if isinstance(gg, dict) else []
        gkw["sub_goal_count"] = max(0, len(goals) - 1) if isinstance(goals, list) else 0
        gkw["replanned"] = bool(md.get("refine_replan"))
        gkw["refine_reexec"] = bool(md.get("refine_reexec"))
        ar = md.get("adaptive_risk") or {}
        gkw["adaptive_risk_score"] = float(ar.get("score", 0.0) or 0.0)

    signals = extract_semantic_turn_signals(request, ctx, response)
    pipe = get_semantic_metrics_pipeline()
    snap = pipe.record_turn(
        session_id,
        evidence_count=int(md.get("evidence_count", 0) or 0),
        fusion_confidence=fusion_conf,
        hallucination_risk=hall,
        critic_passed=passed,
        replanned=bool(gkw.get("replanned")),
        refine_reexec=bool(gkw.get("refine_reexec")),
        goal_transition_rejected=bool(gkw.get("goal_transition_rejected")),
        sub_goal_count=int(gkw.get("sub_goal_count", 0) or 0),
        route=route,
        reflection_round=int(signals.get("reflection_round", 0) or 0),
        claim_conflicts=int(signals.get("claim_conflicts", 0) or 0),
        coverage_score=signals.get("coverage_score"),
        goal_supervisor_split=bool(signals.get("goal_supervisor_split")),
    )

    out: dict[str, Any] = {
        "cognitive_health": snap.to_dict(),
        "session_trend": pipe.session_trend(session_id),
    }

    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_self_optimizing_runtime_enabled", True)):
            from kernel.runtime.self_optimizing_runtime import (
                compute_optimization_hints,
                maybe_apply_session_hints,
            )

            ar = float(gkw.get("adaptive_risk_score", 0.0) or 0.0)
            report = compute_optimization_hints(
                health=snap.to_dict(),
                adaptive_risk_score=ar,
                replanned=bool(gkw.get("replanned")),
                reflection_round=int(signals.get("reflection_round", 0) or 0),
                coverage_score=signals.get("coverage_score"),
            )
            if ctx is not None:
                maybe_apply_session_hints(ctx, report)
            out["self_optimizing_runtime"] = report.to_metadata().get(
                "self_optimizing_runtime", {}
            )
    except Exception:
        pass

    return out


def record_executive_turn_health(
    *,
    session_id: str,
    result: Any,
    request: Any,
    ctx: Any | None,
    route: str = "cognitive_runtime_v2",
) -> dict[str, Any]:
    """Record turn in semantic metrics pipeline + optional self-optimization hints."""
    from kernel.governance.semantic_metrics_pipeline import get_semantic_metrics_pipeline

    critic = getattr(result, "critic_result", None)
    hall = float(getattr(critic, "hallucination_risk", 0.0) or 0.0) if critic else 0.0
    fusion_conf = (
        float(getattr(result.fusion_result, "confidence", 0.0) or 0.0)
        if getattr(result, "fusion_result", None)
        else 0.0
    )
    gkw = {}
    try:
        from kernel.cognitive_supervisor.run_outcomes import governance_kwargs_from_ctx

        gkw = governance_kwargs_from_ctx(ctx, request)
    except Exception:
        pass

    signals = extract_semantic_turn_signals(request, ctx, result)
    pipe = get_semantic_metrics_pipeline()
    snap = pipe.record_turn(
        session_id,
        evidence_count=len(getattr(result, "evidence_objects", None) or []),
        fusion_confidence=fusion_conf,
        hallucination_risk=hall,
        critic_passed=getattr(critic, "passed", None) if critic else None,
        replanned=bool(gkw.get("replanned")),
        refine_reexec=bool(gkw.get("refine_reexec")),
        goal_transition_rejected=bool(gkw.get("goal_transition_rejected")),
        sub_goal_count=int(gkw.get("sub_goal_count", 0) or 0),
        route=route,
        reflection_round=int(signals.get("reflection_round", 0) or 0),
        claim_conflicts=int(signals.get("claim_conflicts", 0) or 0),
        coverage_score=signals.get("coverage_score"),
        goal_supervisor_split=bool(signals.get("goal_supervisor_split")),
    )

    out: dict[str, Any] = {
        "cognitive_health": snap.to_dict(),
        "session_trend": pipe.session_trend(session_id),
    }

    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_self_optimizing_runtime_enabled", True)):
            from kernel.runtime.self_optimizing_runtime import (
                compute_optimization_hints,
                maybe_apply_session_hints,
            )

            ar = float(gkw.get("adaptive_risk_score", 0.0) or 0.0)
            report = compute_optimization_hints(
                health=snap.to_dict(),
                adaptive_risk_score=ar,
                replanned=bool(gkw.get("replanned")),
                reflection_round=int(signals.get("reflection_round", 0) or 0),
                coverage_score=signals.get("coverage_score"),
            )
            if ctx is not None:
                maybe_apply_session_hints(ctx, report)
            out["self_optimizing_runtime"] = report.to_metadata().get(
                "self_optimizing_runtime", {}
            )
    except Exception:
        pass

    return out