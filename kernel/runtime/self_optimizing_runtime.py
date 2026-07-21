"""Self-optimizing runtime — bounded tuning hints from turn outcomes (governance-capped)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OptimizationHint:
    dimension: str  # replan_budget | critic_threshold | capability_preference | context_tokens
    action: str  # tighten | relax | prefer | avoid
    delta: float = 0.0
    reason: str = ""
    capped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "action": self.action,
            "delta": round(self.delta, 4),
            "reason": self.reason[:200],
            "capped": self.capped,
        }


@dataclass
class SelfOptimizationReport:
    hints: list[OptimizationHint] = field(default_factory=list)
    applied: bool = False
    session_id: str = ""

    def to_metadata(self) -> dict[str, Any]:
        return {
            "self_optimizing_runtime": {
                "hint_count": len(self.hints),
                "applied": self.applied,
                "hints": [h.to_dict() for h in self.hints],
            }
        }


def compute_optimization_hints(
    *,
    health: dict[str, Any] | None,
    adaptive_risk_score: float = 0.0,
    replanned: bool = False,
    reflection_round: int = 0,
    coverage_score: float | None = None,
) -> SelfOptimizationReport:
    """Deterministic hints; never bypass governance — metadata only unless apply enabled."""
    hints: list[OptimizationHint] = []
    h = health or {}
    drift = float(h.get("reasoning_drift", 0.0) or 0.0)
    saturation = float(h.get("cognitive_saturation", 0.0) or 0.0)

    if drift > 0.55 or adaptive_risk_score > 0.65:
        hints.append(
            OptimizationHint(
                dimension="critic_threshold",
                action="tighten",
                delta=0.05,
                reason="high_reasoning_drift_or_risk",
            )
        )
    if replanned and reflection_round >= 2:
        hints.append(
            OptimizationHint(
                dimension="replan_budget",
                action="tighten",
                delta=-1.0,
                reason="multiple_cognitive_iterations",
                capped=True,
            )
        )
    if coverage_score is not None and coverage_score < 0.4:
        hints.append(
            OptimizationHint(
                dimension="capability_preference",
                action="prefer",
                delta=0.1,
                reason="low_web_coverage_boost_web_intelligence",
            )
        )
    if saturation > 0.7:
        hints.append(
            OptimizationHint(
                dimension="context_tokens",
                action="relax",
                delta=-256.0,
                reason="cognitive_saturation_compress_context",
                capped=True,
            )
        )
    return SelfOptimizationReport(hints=hints)


def maybe_apply_session_hints(
    ctx: Any,
    report: SelfOptimizationReport,
) -> SelfOptimizationReport:
    from infra.config.settings import settings

    if not bool(getattr(settings, "kernel_self_optimizing_runtime_enabled", True)):
        return report
    if not bool(getattr(settings, "kernel_self_optimizing_runtime_apply", False)):
        md = getattr(ctx, "metadata", None) or {}
        md.update(report.to_metadata())
        ctx.metadata = md
        return report

    md = getattr(ctx, "metadata", None) or {}
    budget = dict(md.get("cognitive_budget_projection") or getattr(ctx, "cognitive_budget", None) or {})
    for hint in report.hints:
        if hint.dimension == "replan_budget" and hint.action == "tighten":
            max_r = int(budget.get("max_replans", 2) or 2)
            budget["max_replans"] = max(0, max_r + int(hint.delta))
            hint.capped = True
    md["cognitive_budget_projection"] = budget
    md.update(report.to_metadata())
    report.applied = True
    ctx.metadata = md
    if budget:
        ctx.cognitive_budget = budget
    return report