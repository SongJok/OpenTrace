"""Re-export policy governor from kernel control plane."""

from kernel.governance.policy_governor import PolicyGovernanceResult, PolicyGovernor

PolicyGovernanceDecision = PolicyGovernanceResult

__all__ = ["PolicyGovernor", "PolicyGovernanceResult", "PolicyGovernanceDecision"]