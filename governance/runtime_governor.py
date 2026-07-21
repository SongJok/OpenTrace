"""Re-export runtime governor from kernel control plane (single implementation)."""

from kernel.governance.runtime_governor import RuntimeGovernanceResult, RuntimeGovernor

RuntimeGovernanceDecision = RuntimeGovernanceResult

__all__ = ["RuntimeGovernor", "RuntimeGovernanceResult", "RuntimeGovernanceDecision"]