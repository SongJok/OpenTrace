"""Re-export memory governor from kernel control plane."""

from kernel.governance.memory_governor import MemoryGovernanceResult, MemoryGovernor

MemoryGovernanceDecision = MemoryGovernanceResult

__all__ = ["MemoryGovernor", "MemoryGovernanceResult", "MemoryGovernanceDecision"]