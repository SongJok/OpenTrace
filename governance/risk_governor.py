"""Re-export risk governor from kernel control plane."""

from kernel.governance.risk_governor import RiskGovernanceResult, RiskGovernor

RiskGovernanceDecision = RiskGovernanceResult

__all__ = ["RiskGovernor", "RiskGovernanceResult", "RiskGovernanceDecision"]