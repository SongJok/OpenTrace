"""
确定性追踪 — 用于调试和合规的结构化追踪。

将认知管线中的每个重要事件捕获为带时间戳的结构化 TraceEvent。
与 PromptSnapshot 和 RuntimeSnapshot 结合，
实现完整的执行回放和审计。

追踪事件覆盖：管线阶段转换、LLM 调用、能力调用、
证据生命周期变更和错误。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TraceEventType(str, Enum):
    PIPELINE_START = "pipeline_start"
    PIPELINE_END = "pipeline_end"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    CAPABILITY_INVOKE = "capability_invoke"
    CAPABILITY_RESULT = "capability_result"
    EVIDENCE_CREATED = "evidence_created"
    EVIDENCE_TRANSITION = "evidence_transition"
    EVIDENCE_SUPERSEDED = "evidence_superseded"
    FUSION_START = "fusion_start"
    FUSION_END = "fusion_end"
    CRITIC_RESULT = "critic_result"
    ERROR = "error"
    WARNING = "warning"


@dataclass
class TraceEvent:
    """确定性追踪中的单个事件。"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: TraceEventType = TraceEventType.PHASE_START
    phase: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    request_id: str = ""
    session_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class DeterministicTrace:
    """单次认知执行的完整追踪。

    包含按时间顺序排列的所有 TraceEvent，以及用于
    回放标识的元数据。
    """

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    session_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    events: list[TraceEvent] = field(default_factory=list)
    total_duration_ms: int = 0
    total_llm_calls: int = 0
    total_capability_calls: int = 0
    error_count: int = 0

    def add_event(self, event: TraceEvent) -> None:
        self.events.append(event)
        if event.event_type == TraceEventType.LLM_CALL:
            self.total_llm_calls += 1
        elif event.event_type == TraceEventType.CAPABILITY_INVOKE:
            self.total_capability_calls += 1
        elif event.event_type == TraceEventType.ERROR:
            self.error_count += 1

    def get_events_by_type(self, event_type: TraceEventType) -> list[TraceEvent]:
        return [e for e in self.events if e.event_type == event_type]

    def get_events_by_phase(self, phase: str) -> list[TraceEvent]:
        return [e for e in self.events if e.phase == phase]

    def get_errors(self) -> list[TraceEvent]:
        return self.get_events_by_type(TraceEventType.ERROR)

    def timeline(self) -> list[dict[str, Any]]:
        """用于可视化的时间线摘要。"""
        return [
            {
                "timestamp": e.timestamp,
                "type": e.event_type.value,
                "phase": e.phase,
                "duration_ms": e.duration_ms,
            }
            for e in sorted(self.events, key=lambda x: x.timestamp)
        ]

    def summary(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "total_events": len(self.events),
            "total_duration_ms": self.total_duration_ms,
            "total_llm_calls": self.total_llm_calls,
            "total_capability_calls": self.total_capability_calls,
            "error_count": self.error_count,
            "phases": list(dict.fromkeys(e.phase for e in self.events if e.phase)),
        }

    def is_replayable(self) -> bool:
        """追踪可回放的条件：无错误且所有 LLM 调用已捕获。"""
        return self.error_count == 0 and self.total_llm_calls > 0
