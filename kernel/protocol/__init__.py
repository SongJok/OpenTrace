"""协议层 — 认知 / 策略 / 运行域之间的稳定契约。"""

from kernel.protocol.cognition_protocol import (
    CognitionEnvelope,
    CognitionPhase,
    PlanningArtifact,
)
from kernel.protocol.runtime_contract import (
    ArtifactState,
    Budget,
    CapabilityRef,
    Constraints,
    EvidencePolicy,
    ExecutionPolicy,
    ExecutionTrace,
    Goal,
    GoalGraph,
    Provenance,
    RuntimeArtifact,
    RuntimeContextRef,
    RuntimeTask,
)
from kernel.protocol.runtime_protocol import (
    ExecutionUnitRef,
    RuntimeEnvelope,
    RuntimePhase,
)

__all__ = [
    "Goal",
    "GoalGraph",
    "RuntimeTask",
    "RuntimeArtifact",
    "RuntimeContextRef",
    "CapabilityRef",
    "Constraints",
    "Budget",
    "EvidencePolicy",
    "ExecutionPolicy",
    "ExecutionTrace",
    "Provenance",
    "ArtifactState",
    "CognitionEnvelope",
    "CognitionPhase",
    "PlanningArtifact",
    "RuntimeEnvelope",
    "RuntimePhase",
    "ExecutionUnitRef",
]