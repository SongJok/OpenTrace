"""认知运行时契约 — 通用认知运行时的规范类型。

下列类型是稳定边界：
  - 认知域（规划、目标、约束）
  - 策略域（能力、策略、预算）
  - 运行域（DAG 执行、证据、制品）

回放、审计、治理与分布式运行时均依赖本契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ArtifactState(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@dataclass
class Goal:
    """Atomic goal node — building block of GoalGraph."""

    goal_id: str
    description: str
    priority: int = 0
    parent_id: str | None = None
    success_criteria: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GoalGraph:
    """First-class goal structure: User Query → Intent → Goal Graph → Execution Projection."""

    root_goal_id: str
    goals: list[Goal] = field(default_factory=list)
    intent_category: str = "general"
    protected_intent: str = ""

    def add_goal(self, goal: Goal) -> None:
        self.goals.append(goal)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_goal_id": self.root_goal_id,
            "intent_category": self.intent_category,
            "protected_intent": self.protected_intent,
            "goals": [
                {
                    "goal_id": g.goal_id,
                    "description": g.description,
                    "priority": g.priority,
                    "parent_id": g.parent_id,
                    "success_criteria": g.success_criteria,
                }
                for g in self.goals
            ],
        }


@dataclass
class Constraints:
    """Runtime constraints applied before execution projection."""

    allowed_capabilities: list[str] = field(default_factory=list)
    disallowed_capabilities: list[str] = field(default_factory=list)
    max_parallel: int = 5
    max_depth: int = 3
    relevance_threshold: float = 0.35
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityRef:
    """Capability binding — not a tool name."""

    capability_type: str
    capability_name: str = ""
    strategy_hint: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Budget:
    """Execution budget (runtime-facing; see protocol.governance for governance budgets)."""

    max_tokens: int = 10000
    max_steps: int = 10
    max_llm_calls: int = 5
    max_time_seconds: float = 60.0
    max_replans: int = 1


@dataclass
class EvidencePolicy:
    min_evidence_count: int = 0
    require_citations: bool = False
    rank_before_fusion: bool = True
    resolve_contradictions: bool = True


@dataclass
class ExecutionPolicy:
    capability_executor_mode: bool = False
    timeout_sec: int = 30
    sandbox_required: bool = False
    fallback_to_direct_answer: bool = True


@dataclass
class RuntimeContextRef:
    """Lightweight reference to session-scoped runtime context (full object lives in runtime.context)."""

    request_id: str
    session_id: str
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeTask:
    """Unit of work submitted to Universal Cognitive Runtime."""

    id: str
    goal: Goal
    goal_graph: GoalGraph | None = None
    constraints: Constraints = field(default_factory=Constraints)
    capabilities: list[CapabilityRef] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    context: RuntimeContextRef = field(default_factory=lambda: RuntimeContextRef("", ""))
    evidence_policy: EvidencePolicy = field(default_factory=EvidencePolicy)
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    query: str = ""


@dataclass
class Provenance:
    sources: list[str] = field(default_factory=list)
    trace_id: str = ""
    planner_version: str = "cognitive_runtime_v2"


@dataclass
class ExecutionTrace:
    phases: list[str] = field(default_factory=list)
    duration_ms: int = 0
    agent_errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GoalEvidenceBinding:
    """Typed link between GoalGraph root, artifact, and evidence IDs."""

    root_goal_id: str
    artifact_id: str
    evidence_ids: list[str] = field(default_factory=list)
    session_id: str = ""
    binding_version: str = "goal_evidence_v1"


@dataclass
class RuntimeArtifact:
    """Durable output of a runtime turn."""

    artifact_id: str
    evidence: list[Any] = field(default_factory=list)
    execution_trace: ExecutionTrace = field(default_factory=ExecutionTrace)
    confidence: float = 0.0
    provenance: Provenance = field(default_factory=Provenance)
    state: ArtifactState = ArtifactState.DRAFT
    content: str = ""
    goal_evidence_binding: GoalEvidenceBinding | None = None
    metadata: dict[str, Any] = field(default_factory=dict)