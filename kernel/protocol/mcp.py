"""Multi-Agent Cognitive Protocol types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    source: str = ""
    content: str = ""
    relevance: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hypothesis:
    statement: str = ""
    confidence: float = 0.0
    supporting_evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Action:
    action_type: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


@dataclass
class ActionPlan:
    goal: str = ""
    actions: list[Action] = field(default_factory=list)
    fallback_actions: list[Action] = field(default_factory=list)


@dataclass
class Critique:
    assessment: str = ""
    score: float = 0.0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class AgentTrace:
    agent_type: str = ""
    task_id: str = ""
    input_summary: str = ""
    output_summary: str = ""
    confidence: float = 0.0
    latency_ms: float = 0.0
    llm_calls: int = 0


class FailureTag:
    HALLUCINATION = "hallucination"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    API_ERROR = "api_error"
    VALIDATION_ERROR = "validation_error"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTION = "contradiction"


@dataclass
class CognitiveContext:
    query: str = ""
    intent: str = ""
    entities: list[str] = field(default_factory=list)
    time_window: str = ""
    session_id: str = ""
    user_id: str = ""
    data_source_id: str = ""
