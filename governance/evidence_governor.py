"""Re-export evidence governor from kernel control plane."""

from kernel.governance.evidence_governor import EvidenceGovernanceResult, EvidenceGovernor

EvidenceGovernanceDecision = EvidenceGovernanceResult

__all__ = ["EvidenceGovernor", "EvidenceGovernanceResult", "EvidenceGovernanceDecision"]