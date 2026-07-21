"""Adaptive risk scoring — canonical implementation (kernel.governance)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AdaptiveRiskScore:
    level: str = "low"
    score: float = 0.0
    factors: list[str] = field(default_factory=list)


class AdaptiveRiskEngine:
    def score_turn(
        self,
        *,
        hallucination_risk: float = 0.0,
        replanned: bool = False,
        evidence_count: int = 0,
        sub_goal_count: int = 0,
    ) -> AdaptiveRiskScore:
        score = hallucination_risk * 0.5
        factors: list[str] = []
        if replanned:
            score += 0.15
            factors.append("replanned")
        if evidence_count == 0 and sub_goal_count > 0:
            score += 0.2
            factors.append("no_evidence_multi_goal")
        if sub_goal_count > 4:
            score += 0.1
            factors.append("many_sub_goals")
        level = "low"
        if score >= 0.6:
            level = "high"
        elif score >= 0.35:
            level = "medium"
        return AdaptiveRiskScore(level=level, score=min(1.0, score), factors=factors)