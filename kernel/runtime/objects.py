"""
RuntimeObject and Evidence — unified object model for the Cognitive Runtime.

All data flowing through the system (agent results, tool outputs, memories,
artifacts) share the RuntimeObject base.  Evidence is the primary unit of
information exchange between Agents and the Fusion / Critic engines.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class ObjectType(str, Enum):
    EVIDENCE = "evidence"
    ARTIFACT = "artifact"
    AGENT_RESULT = "agent_result"
    TOOL_RESULT = "tool_result"
    MEMORY = "memory"
    MESSAGE = "message"


# ── Provenance ───────────────────────────────────────────────────────────────

class Provenance(BaseModel):
    """Where a piece of evidence came from and how much we trust its source."""

    source: str = ""  # agent_type ("data", "rag", "web", "tool", "skills")
    source_type: str = "agent"  # "agent" | "tool" | "human" | "synthesized"
    confidence: float = 0.5
    timestamp: datetime | None = None
    trace_id: str = ""


# ── Evidence — the primary information currency ──────────────────────────────

class Evidence(BaseModel):
    """Structured evidence produced by an Agent or Tool.

    Every Capability MUST return Evidence (or an Artifact / RuntimeObject)
    instead of raw unstructured text.  The Fusion and Critic engines consume
    Evidence exclusively.

    Evidence follows a state-machine lifecycle:
      CREATED → VALIDATED → RANKED → MERGED → ARCHIVED
                      ↓         ↓         ↓
                  INVALIDATED  SUPERSEDED  SUPERSEDED
    """

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    content_type: str = "text"  # "text" | "table" | "chart" | "code" | "image"
    provenance: Provenance = Field(default_factory=Provenance)
    credibility_score: float = 0.5
    relevance_score: float = 0.5
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    state: str = "created"  # EvidenceState value — "created" | "validated" | "ranked" | "merged" | "superseded" | "archived" | "invalidated"
    version: int = 1  # Monotonic version counter; increments on supersede
    superseded_by: str = ""  # evidence_id of the evidence that replaced this one
    supersedes: str = ""     # evidence_id of the evidence this one replaces
    lineage: list[str] = Field(default_factory=list)  # Chain of evidence_ids this derives from


# ── RuntimeObject — base for all persistent runtime entities ─────────────────

class RuntimeObject(BaseModel):
    """Base class for every object that flows through the Runtime.

    Message, Memory, Artifact, ToolResult, AgentResult — all share this base.
    """

    object_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    object_type: ObjectType = ObjectType.EVIDENCE
    session_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: Provenance | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Runtime Canonical Query ─────────────────────────────────────────────────


@dataclass
class RuntimeCanonicalQuery:
    """Fully-resolved, normalized query produced by the RewriteEngine.

    Fuses multi-turn conversation, user profile, workspace state,
    historical artifacts, memory context, and organizational policy
    into a single canonical representation of what the user actually wants.
    """

    raw_query: str = ""
    normalized_query: str = ""
    protected_intent: str = ""
    canonical_query: str = ""
    original_query: str = ""
    context_blocks: list[str] = field(default_factory=list)
    entity_resolutions: dict[str, str] = field(default_factory=dict)
    workspace_references: list[str] = field(default_factory=list)
    artifact_references: list[str] = field(default_factory=list)
    policy_constraints: list[str] = field(default_factory=list)
    rewrite_trace: str = ""


# ── Understanding Result ───────────────────────────────────────────────────


@dataclass
class UnderstandingResult:
    """Deep cognitive understanding produced by the UnderstandingEngine.

    Not intent classification — true task comprehension:
    what the user explicitly wants, what they implicitly need,
    what constraints apply, and what success looks like.
    """

    raw_query: str = ""
    normalized_query: str = ""
    protected_intent: str = ""
    planning_hints: list[str] = field(default_factory=list)
    expanded_context: list[str] = field(default_factory=list)
    intent_confidence: float = 0.0
    explicit_goal: str = ""
    hidden_goal: str = ""
    entities: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    ambiguity: str = ""
    risk_level: str = "low"
    expected_output_type: str = "text"
    required_capabilities: list[str] = field(default_factory=list)
    execution_strategy: str = "direct"
    completion_criteria: str = ""
    domain: str = ""


# ── Execution Plan ─────────────────────────────────────────────────────────


@dataclass
class ExecutionTask:
    """A single task within an ExecutionPlan, bound to a capability."""

    task_id: str = ""
    capability_type: str = ""  # "data.query", "web.search", "rag.retrieve", etc.
    query: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    priority: str = "normal"  # high | normal | low
    reason: str = ""
    expected_evidence_type: str = "text"
    goal_id: str = ""

    @property
    def agent_type(self) -> str:
        """Backward-compat: extract agent_type from capability_type."""
        return self.capability_type.split(".")[0] if "." in self.capability_type else self.capability_type

    @property
    def sub_question_id(self) -> str:
        """Backward-compat alias for task_id."""
        return self.task_id


@dataclass
class ExecutionPlan:
    """Complete execution plan produced by the CognitivePlanner.

    One LLM call generates the entire graph — no incremental planning,
    no runtime agent discovery, no autonomous fallback.
    """

    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rewritten_query: str = ""
    intent_category: str = ""
    understanding_summary: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    subtasks: list[ExecutionTask] = field(default_factory=list)
    merge_strategy: str = "union"
    risk_level: str = "low"
    completion_criteria: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Execution Graph ────────────────────────────────────────────────────────


@dataclass
class ExecutionBudget:
    """Resource budget for a single execution node."""

    max_tokens: int = 4096
    max_latency_ms: int = 30000
    max_cost: float = 0.0


@dataclass
class ExecutionNode:
    """A node in the ExecutionGraph — one capability invocation."""

    node_id: str = ""
    capability_name: str = ""
    executor_type: str = ""  # resolved from CapabilityRegistry
    query: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    resource: str = "CPU"  # CPU | GPU | IO
    priority: str = "normal"
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    expected_evidence_schema: dict[str, Any] = field(default_factory=dict)
    goal_id: str = ""


@dataclass
class ExecutionEdge:
    """Directed edge in the ExecutionGraph — data dependency."""

    from_node: str = ""
    to_node: str = ""
    data_dependency: str = ""  # what data flows from source to target
