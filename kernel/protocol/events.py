"""Cognitive event protocol types."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any


class SpanStage(str, enum.Enum):
    INPUT = "input"
    PROCESSING = "processing"
    OUTPUT = "output"
    GATEWAY = "gateway"
    PLANNING = "planning"
    DISPATCH = "dispatch"
    AGENT_EXECUTION = "agent_execution"
    FUSION = "fusion"
    CRITIC = "critic"
    FINAL = "final"


class CognitiveEventTypeV2(str, enum.Enum):
    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"
    DECISION = "decision"


@dataclass
class CognitiveEventV2:
    type: CognitiveEventTypeV2
    stage: SpanStage = SpanStage.PROCESSING
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceContext:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: str | None = None

    @property
    def root_span_id(self) -> str:
        return self.span_id

    def start_span(self, name: str = "", parent_span_id: str | None = None) -> str:
        new_span_id = str(uuid.uuid4())
        # Store the new span in a lineage dict for later retrieval
        if not hasattr(self, "_spans"):
            self._spans: dict[str, dict[str, Any]] = {}
        self._spans[new_span_id] = {
            "name": name,
            "parent_span_id": parent_span_id or self.span_id,
        }
        return new_span_id


def trace_context_for_request(
    request_id: str = "",
    session_id: str = "",
    user_id: str = "",
) -> TraceContext:
    return TraceContext()
