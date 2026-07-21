"""
Executive-level reflection → replan loop (distinct from DataAgent V2 reflection_agent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CognitiveIterationState:
    round: int = 0
    max_rounds: int = 1
    triggered: bool = False
    replan_reason: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "cognitive_iteration": {
                "reflection_round": self.round,
                "max_cognitive_iterations": self.max_rounds,
                "replan_triggered": self.triggered,
                "replan_reason": self.replan_reason,
                "history": list(self.history),
            }
        }


def _max_iterations(settings: Any) -> int:
    explicit = int(getattr(settings, "kernel_cognitive_iteration_max", 2) or 2)
    revise = int(getattr(settings, "kernel_revise_max_iterations", 3) or 3)
    return max(1, min(explicit, revise))


def should_trigger_cognitive_replan(
    *,
    critic_result: Any,
    evidence_count: int,
    fusion_confidence: float,
    ctx: Any,
) -> tuple[bool, str]:
    """Decide if executive should replan after critic / evidence gates."""
    from infra.config.settings import settings

    if not bool(getattr(settings, "kernel_cognitive_iteration_enabled", True)):
        return False, "disabled"
    md = getattr(ctx, "metadata", None) or {}
    state = md.get("cognitive_iteration") or {}
    current = int(state.get("reflection_round", 0) or 0)
    if current >= _max_iterations(settings):
        return False, "max_iterations_reached"

    budget = getattr(ctx, "cognitive_budget", None) or md.get("cognitive_budget_projection") or {}
    max_replans = int(budget.get("max_replans", 1) or 1)
    replans_used = int(md.get("cognitive_replans_used", 0) or 0)
    if replans_used >= max_replans:
        return False, "budget_max_replans"

    if critic_result is not None and not getattr(critic_result, "passed", True):
        hall = float(getattr(critic_result, "hallucination_risk", 0.0) or 0.0)
        if hall >= 0.45:
            return True, "critic_hallucination_risk"
        fact = float(getattr(critic_result, "factuality", 1.0) or 1.0)
        if fact < 0.55:
            return True, "critic_low_factuality"

    min_ev = 1 if evidence_count == 0 else 0
    if evidence_count <= min_ev and fusion_confidence < 0.5:
        return True, "insufficient_evidence"

    gg = md.get("goal_graph") or {}
    goals = gg.get("goals") or []
    if len(goals) > 2 and fusion_confidence < 0.6:
        return True, "multi_goal_low_confidence"

    return False, ""


def record_iteration_round(ctx: Any, reason: str) -> CognitiveIterationState:
    from infra.config.settings import settings

    md = getattr(ctx, "metadata", None) or {}
    prev = md.get("cognitive_iteration") or {}
    rnd = int(prev.get("reflection_round", 0) or 0) + 1
    state = CognitiveIterationState(
        round=rnd,
        max_rounds=_max_iterations(settings),
        triggered=True,
        replan_reason=reason,
        history=list(prev.get("history") or []) + [{"round": rnd, "reason": reason}],
    )
    md["cognitive_iteration"] = state.to_metadata()["cognitive_iteration"]
    md["cognitive_replans_used"] = int(md.get("cognitive_replans_used", 0) or 0) + 1
    md["reflection_round"] = rnd
    md["replan_reason"] = reason
    ctx.metadata = md
    return state


async def maybe_executive_replan(
    *,
    canonical_query: str,
    ctx: Any,
    plan: Any,
    agent_results: list[Any],
    critic_result: Any,
    evidence_objects: list[Any],
    execution_runtime: Any,
    event_cb: Any,
    fusion_confidence: float = 0.0,
) -> tuple[Any, list[Any], bool]:
    """
    Reflection → Replan → optional re-execute.
    Returns (plan, agent_results, replanned).
    """
    trigger, reason = should_trigger_cognitive_replan(
        critic_result=critic_result,
        evidence_count=len(evidence_objects),
        fusion_confidence=fusion_confidence,
        ctx=ctx,
    )
    if not trigger:
        return plan, agent_results, False

    record_iteration_round(ctx, reason)
    try:
        from kernel.cognition.planner_facade import RefinementPlanner
        from kernel.refine_planner import RepairStrategy
        from infra.config.settings import settings

        plan, agent_results, replanned, refined_info = await RefinementPlanner().maybe_replan_after_failures(
            canonical_query, plan, agent_results, depth=int((ctx.metadata or {}).get("cognitive_replans_used", 1))
        )
        if not replanned:
            return plan, agent_results, False
        ctx.metadata = ctx.metadata or {}
        ctx.metadata["cognitive_iteration_replan"] = {
            "strategy": refined_info.repair_strategy.value if refined_info else "unknown",
            "reason": reason,
        }
        if (
            getattr(settings, "kernel_refine_reexec_enabled", True)
            and refined_info is not None
            and refined_info.repair_strategy
            in {
                RepairStrategy.RETRY,
                RepairStrategy.SUBSTITUTE,
                RepairStrategy.SIMPLIFY,
                RepairStrategy.PREPEND,
            }
        ):
            retry_results = await execution_runtime.execute(
                plan=plan,
                ctx=ctx,
                event_cb=event_cb,
                capability_executor_mode=bool(settings.kernel_agent_capability_executor_mode),
                execution_graph=None,
            )
            if retry_results:
                agent_results = retry_results
        return plan, agent_results, True
    except Exception:
        return plan, agent_results, False