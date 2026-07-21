"""Evidence fusion / write policy — canonical."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvidencePolicyDecision:
    allow_fusion: bool = True
    min_count: int = 0
    require_rank: bool = True
    violations: list[str] = field(default_factory=list)


class EvidencePolicyEngine:
    def evaluate_fusion(
        self,
        *,
        evidence_count: int,
        min_required: int = 0,
        hallucination_risk: float = 0.0,
    ) -> EvidencePolicyDecision:
        violations: list[str] = []
        if evidence_count < min_required:
            violations.append("insufficient_evidence")
        if hallucination_risk > 0.85:
            violations.append("hallucination_risk_high")
        return EvidencePolicyDecision(
            allow_fusion=len(violations) == 0,
            min_count=min_required,
            require_rank=True,
            violations=violations,
        )