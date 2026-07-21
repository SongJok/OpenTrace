"""风险治理 — 幻觉与策略风险信号。"""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class RiskGovernanceResult:
    level: str = "low"
    blocked: bool = False
    signals: list[str] = field(default_factory=list)

class RiskGovernor:
    def assess(self, hallucination_risk: float, policy_denied: bool = False) -> RiskGovernanceResult:
        if policy_denied:
            return RiskGovernanceResult(level="critical", blocked=True, signals=["policy_denied"])
        if hallucination_risk >= 0.8:
            return RiskGovernanceResult(level="high", blocked=False, signals=["high_hallucination_risk"])
        if hallucination_risk >= 0.5:
            return RiskGovernanceResult(level="medium", signals=["elevated_hallucination_risk"])
        return RiskGovernanceResult(level="low")