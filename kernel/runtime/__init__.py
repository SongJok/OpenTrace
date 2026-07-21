"""
OpenTrace Cognitive Runtime — Unified infrastructure for the AI OS kernel.

This package provides the unified entry point, context model, object model,
capability registry, execution runtime, evidence bus, and orchestration layer
that converge the previously scattered cognitive pipeline into a single
coherent Runtime.

Pipeline (V2):
  Query → RewriteEngine → UnderstandingEngine → CognitivePlannerV2
  → StrategyBuilder → ExecutionProjection → ExecutionRuntime
  → EvidenceBus (with lifecycle) → FusionEngineV2 → CriticEngineV2
  → ArtifactComposer → Workspace + MemoryFabric (with truth maintenance)

All modules communicate through RuntimeContext + RuntimeEventStore.
No module directly imports another module's internals.
"""

# ── Context ──
from kernel.runtime.artifact_composer import ArtifactComposer

# ── Artifacts & Workspace ──
from kernel.runtime.artifacts import Artifact, ArtifactManager

# ── Capability ──
from kernel.runtime.capability import Capability, CapabilityRegistry, capability_registry
from kernel.runtime.capability_graph_builder import CapabilityGraphBuilder

# ── Cognitive Planning Layer (V2) ──
from kernel.runtime.cognitive import (
    CognitiveConstraint,
    CognitiveGraph,
    CognitivePlan,
    CognitivePlannerV2,
    DecompositionPolicy,
    DecompositionStrategy,
    ExecutionProjection,
    GoalHierarchy,
    GoalNode,
    GoalType,
    InformationGap,
    ProjectedCapability,
    ProjectionGroup,
    ReasoningChain,
    ReasoningStep,
    RiskAnalysis,
    StrategyBuilder,
    StrategyProjection,
    UncertaintyModel,
    build_decomposition_policy,
    build_execution_projection,
    build_strategy_projection,
)

# ── Cognitive Executive (unified entry point) ──
from kernel.runtime.cognitive_executive import CognitiveExecutive, CognitiveExecutiveResult

# ── Constraint Layer ──
from kernel.runtime.constraint_layer import (
    ConstraintDecision,
    PlannerConstraintLayer,
    constraint_layer,
)
from kernel.runtime.context import RuntimeContext

# ── Context Compression Runtime ──
from kernel.runtime.context_runtime import (
    ContextCompressor,
    ContextRanker,
    EvidenceSelector,
    MemorySelector,
    RankedContextBlock,
    SemanticDistiller,
)
from kernel.runtime.critic import CriticEngineV2, CriticResult

# ── Events ──
from kernel.runtime.event_store import RuntimeEvent, RuntimeEventStore
from kernel.runtime.evidence import (
    EvidenceLifecycle,
    EvidenceRanker,
    EvidenceResolution,
    EvidenceState,
    EvidenceStateMachine,
    RankedEvidence,
    ResolutionStrategy,
    resolve_evidence_conflicts,
)

# ── Evidence (with lifecycle) ──
from kernel.runtime.evidence_bus import EvidenceBus, evidence_bus

# ── Execution Reasoning ──
from kernel.runtime.execution_reasoning import (
    CapabilityChoice,
    ExecutionReasoning,
    ExecutionReasoningBuilder,
    ExecutionStepReasoning,
    execution_reasoning_builder,
)

# ── Execution ──
from kernel.runtime.executor import ExecutionRuntime

# ── Fusion & Critic ──
from kernel.runtime.fusion import FusionEngineV2, FusionResult
from kernel.runtime.memory import (
    ContradictionDetector,
    FactSupersessionEngine,
    TruthMaintenanceSystem,
    apply_confidence_decay,
    run_truth_maintenance,
)

# ── Memory (with truth maintenance) ──
from kernel.runtime.memory_fabric import MemoryFabric, memory_fabric

# ── Objects ──
from kernel.runtime.objects import (
    Evidence,
    ExecutionBudget,
    ExecutionEdge,
    ExecutionNode,
    ExecutionPlan,
    ExecutionTask,
    ObjectType,
    Provenance,
    RuntimeCanonicalQuery,
    RuntimeObject,
    UnderstandingResult,
)

# ── Orchestration (legacy, to be deprecated) ──
from kernel.runtime.orchestrator import CognitivePlanner, UnifiedOrchestrator

# ── Policy ──
from kernel.runtime.policy import PolicyDecision, PolicyRule, UnifiedPolicyEngine, policy_engine

# ── Replay ──
from kernel.runtime.replay import (
    DeterministicTrace,
    ExecutionReplay,
    PromptSnapshot,
    PromptSnapshotStore,
    ReplayResult,
    RuntimeSnapshot,
    RuntimeSnapshotStore,
    TraceEvent,
    TraceEventType,
    prompt_snapshot_store,
    runtime_snapshot_store,
)

# ── Engines ──
from kernel.runtime.rewrite_engine import RewriteEngine
from kernel.runtime.understanding_engine import UnderstandingEngine
from kernel.runtime.workspace import Workspace, WorkspaceManager

__all__ = [
    # Context
    "RuntimeContext",
    # Objects
    "RuntimeObject",
    "ObjectType",
    "Evidence",
    "Provenance",
    "RuntimeCanonicalQuery",
    "UnderstandingResult",
    "ExecutionTask",
    "ExecutionPlan",
    "ExecutionBudget",
    "ExecutionNode",
    "ExecutionEdge",
    # Capability
    "Capability",
    "CapabilityRegistry",
    "capability_registry",
    "CapabilityGraphBuilder",
    # Execution
    "ExecutionRuntime",
    # Evidence
    "EvidenceBus",
    "evidence_bus",
    "EvidenceState",
    "EvidenceStateMachine",
    "EvidenceLifecycle",
    "EvidenceRanker",
    "RankedEvidence",
    "EvidenceResolution",
    "ResolutionStrategy",
    "resolve_evidence_conflicts",
    # Cognitive Planning V2
    "CognitiveGraph",
    "CognitivePlan",
    "CognitiveConstraint",
    "GoalNode",
    "GoalType",
    "GoalHierarchy",
    "UncertaintyModel",
    "InformationGap",
    "ReasoningChain",
    "ReasoningStep",
    "RiskAnalysis",
    "CognitivePlannerV2",
    "StrategyBuilder",
    "StrategyProjection",
    "DecompositionPolicy",
    "DecompositionStrategy",
    "build_decomposition_policy",
    "ExecutionProjection",
    "ProjectedCapability",
    "ProjectionGroup",
    "build_execution_projection",
    "build_strategy_projection",
    # Context Compression
    "ContextCompressor",
    "ContextRanker",
    "RankedContextBlock",
    "SemanticDistiller",
    "MemorySelector",
    "EvidenceSelector",
    # Memory
    "MemoryFabric",
    "memory_fabric",
    "TruthMaintenanceSystem",
    "ContradictionDetector",
    "FactSupersessionEngine",
    "apply_confidence_decay",
    "run_truth_maintenance",
    # Replay
    "PromptSnapshot",
    "PromptSnapshotStore",
    "prompt_snapshot_store",
    "RuntimeSnapshot",
    "RuntimeSnapshotStore",
    "runtime_snapshot_store",
    "ExecutionReplay",
    "ReplayResult",
    "DeterministicTrace",
    "TraceEvent",
    "TraceEventType",
    # Orchestration (legacy)
    "UnifiedOrchestrator",
    "CognitivePlanner",
    # Engines
    "RewriteEngine",
    "UnderstandingEngine",
    # Fusion & Critic
    "FusionEngineV2",
    "FusionResult",
    "CriticEngineV2",
    "CriticResult",
    # Events
    "RuntimeEvent",
    "RuntimeEventStore",
    # Policy
    "PolicyDecision",
    "PolicyRule",
    "UnifiedPolicyEngine",
    "policy_engine",
    # Constraint Layer
    "ConstraintDecision",
    "PlannerConstraintLayer",
    "constraint_layer",
    # Artifacts
    "Artifact",
    "ArtifactManager",
    "ArtifactComposer",
    # Workspace
    "Workspace",
    "WorkspaceManager",
    # Execution Reasoning
    "CapabilityChoice",
    "ExecutionReasoning",
    "ExecutionReasoningBuilder",
    "ExecutionStepReasoning",
    "execution_reasoning_builder",
    # Cognitive Executive
    "CognitiveExecutive",
    "CognitiveExecutiveResult",
]
