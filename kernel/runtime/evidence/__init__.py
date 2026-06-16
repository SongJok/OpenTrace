"""
Evidence Lifecycle Layer — Stateful evidence management for the Cognitive Runtime.

Prevents EvidencePool from becoming a garbage dump by enforcing a structured
lifecycle: CREATED → VALIDATED → RANKED → MERGED → SUPERSEDED → ARCHIVED.

All evidence flowing through the system passes through this state machine.
"""

from kernel.runtime.evidence.lifecycle import EvidenceLifecycle
from kernel.runtime.evidence.ranking import EvidenceRanker, RankedEvidence
from kernel.runtime.evidence.resolution import (
    EvidenceResolution,
    ResolutionStrategy,
    resolve_evidence_conflicts,
)
from kernel.runtime.evidence.state_machine import (
    EvidenceState,
    EvidenceStateMachine,
    InvalidTransitionError,
    state_transition,
)

__all__ = [
    "EvidenceState",
    "EvidenceStateMachine",
    "EvidenceLifecycle",
    "state_transition",
    "InvalidTransitionError",
    "EvidenceRanker",
    "RankedEvidence",
    "EvidenceResolution",
    "ResolutionStrategy",
    "resolve_evidence_conflicts",
]
