from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExecutionStage(str, Enum):
    REASON = "REASON"
    DECIDE = "DECIDE"
    EXECUTE = "EXECUTE"
    OBSERVE = "OBSERVE"
    REFLECT = "REFLECT"


class StepType(str, Enum):
    REASON = "REASON"
    DECIDE = "DECIDE"
    EXECUTE = "EXECUTE"
    OBSERVE = "OBSERVE"
    REFLECT = "REFLECT"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecutionNodeType(str, Enum):
    LLM = "LLM"
    TOOL = "TOOL"
    MEMORY = "MEMORY"
    RAG = "RAG"
    REFLECT = "REFLECT"


class ExecutionNodeStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionNode(BaseModel):
    id: str
    type: ExecutionNodeType
    stage: ExecutionStage
    status: ExecutionNodeStatus = ExecutionNodeStatus.PENDING
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    start_time: datetime | None = None
    end_time: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionEdge(BaseModel):
    source: str
    target: str


class ExecutionGraph(BaseModel):
    nodes: list[ExecutionNode] = Field(default_factory=list)
    edges: list[ExecutionEdge] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)


class AgentStep(BaseModel):
    step_id: str
    step_type: StepType
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: StepStatus = StepStatus.PENDING
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    reasoning_chain: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    observation: str | None = None
    reflection_score: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    execution_node_id: str | None = None


class AgentState(BaseModel):
    session_id: str
    user_id: str
    query: str
    steps: list[AgentStep] = Field(default_factory=list)
    current_step_index: int = 0
    final_response: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    checkpoints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    execution_graph: ExecutionGraph = Field(default_factory=ExecutionGraph)
