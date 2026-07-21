"""语义操作系统指标 — 除错误率外的认知健康度（canonical）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CognitiveHealthSnapshot:
    reasoning_drift: float = 0.0
    goal_stability: float = 1.0
    capability_entropy: float = 0.0
    memory_pollution_risk: float = 0.0
    evidence_integrity: float = 1.0
    planner_volatility: float = 0.0
    runtime_recovery_score: float = 1.0
    cognitive_saturation: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_cognitive_health(
    *,
    evidence_count: int,
    fusion_confidence: float,
    hallucination_risk: float,
    critic_passed: bool | None,
    replanned: bool = False,
    refine_reexec: bool = False,
    goal_transition_rejected: bool = False,
    sub_goal_count: int = 0,
    reflection_round: int = 0,
    claim_conflicts: int = 0,
    coverage_score: float | None = None,
    goal_supervisor_split: bool = False,
) -> CognitiveHealthSnapshot:
    """基于单回合启发式计算认知健康度。"""
    evidence_integrity = min(1.0, evidence_count / max(1, 1 + sub_goal_count))
    if fusion_confidence > 0:
        evidence_integrity = max(evidence_integrity, min(1.0, fusion_confidence))

    goal_stability = 0.7 if goal_transition_rejected else 1.0
    planner_volatility = 0.35 if replanned else 0.0
    if refine_reexec:
        planner_volatility = min(1.0, planner_volatility + 0.25)

    runtime_recovery = 0.5 if replanned and critic_passed else (1.0 if critic_passed is not False else 0.6)
    capability_entropy = min(1.0, sub_goal_count * 0.15 + (0.2 if replanned else 0.0))
    memory_pollution = 0.3 if hallucination_risk > 0.5 else hallucination_risk * 0.4
    cognitive_saturation = min(1.0, hallucination_risk + planner_volatility * 0.5)
    reasoning_drift = hallucination_risk * 0.8 + (0.2 if not critic_passed and critic_passed is not None else 0.0)
    if reflection_round > 0:
        planner_volatility = min(1.0, planner_volatility + reflection_round * 0.12)
    if claim_conflicts > 0:
        evidence_integrity = max(0.0, evidence_integrity - min(0.4, claim_conflicts * 0.15))
    extra: dict[str, Any] = {
        "reflection_round": reflection_round,
        "claim_conflicts": claim_conflicts,
        "goal_supervisor_split": goal_supervisor_split,
    }
    if coverage_score is not None:
        extra["coverage_score"] = round(float(coverage_score), 4)
        if coverage_score < 0.5:
            cognitive_saturation = min(1.0, cognitive_saturation + 0.1)

    return CognitiveHealthSnapshot(
        reasoning_drift=round(reasoning_drift, 4),
        goal_stability=round(goal_stability, 4),
        capability_entropy=round(capability_entropy, 4),
        memory_pollution_risk=round(memory_pollution, 4),
        evidence_integrity=round(evidence_integrity, 4),
        planner_volatility=round(planner_volatility, 4),
        runtime_recovery_score=round(runtime_recovery, 4),
        cognitive_saturation=round(cognitive_saturation, 4),
        extra=extra,
    )