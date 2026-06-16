"""Re-export capability governor from kernel control plane."""

from kernel.governance.capability_governor import (
    CapabilityGovernanceResult,
    CapabilityGovernor,
)

CapabilityGovernanceDecision = CapabilityGovernanceResult

__all__ = ["CapabilityGovernor", "CapabilityGovernanceResult", "CapabilityGovernanceDecision"]