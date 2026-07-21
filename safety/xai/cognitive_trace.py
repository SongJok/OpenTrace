from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)

MAX_TRACE_EVENTS = 500
MAX_STORED_TRACES = 200


@dataclass
class TraceEvent:
    """A single decision point in the cognitive pipeline."""

    timestamp: float = 0.0
    stage: str = ""
    event_type: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


@dataclass
class CognitiveTrace:
    """Complete audit trail for one query."""

    trace_id: str = ""
    session_id: str = ""
    query: str = ""
    user_id: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    events: list[TraceEvent] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class CognitiveTracer:
    """Records structured, explainable audit trails of the cognitive pipeline.

    Usage::

        tracer = CognitiveTracer()
        tid = tracer.start_trace(session_id="s1", query="天气怎么样")
        tracer.record_decision(tid, "PLAN", "plan_generated",
                               {"plan_id": "p1", "subtasks": 3},
                               "Generated 3 subtasks")
    """

    def __init__(self, max_traces: int = MAX_STORED_TRACES) -> None:
        self._max_traces = max_traces
        self._traces: OrderedDict[str, CognitiveTrace] = OrderedDict()

    def start_trace(
        self,
        session_id: str,
        query: str,
        user_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Begin a new cognitive trace. Returns trace_id."""
        tid = str(uuid.uuid4())
        trace = CognitiveTrace(
            trace_id=tid,
            session_id=session_id,
            query=query,
            user_id=user_id,
            started_at=time.time(),
            metadata=metadata or {},
        )
        self._traces[tid] = trace
        self._evict_if_needed()
        logger.info("Cognitive trace started", trace_id=tid, session_id=session_id)
        return tid

    def finish_trace(
        self, trace_id: str, summary: dict[str, Any] | None = None
    ) -> None:
        """Mark a trace as complete with an optional summary."""
        trace = self._traces.get(trace_id)
        if trace is None:
            return
        trace.finished_at = time.time()
        if summary is not None:
            trace.summary = summary
        logger.info(
            "Cognitive trace finished",
            trace_id=trace_id,
            event_count=len(trace.events),
            elapsed_ms=int((trace.finished_at - trace.started_at) * 1000),
        )

    def record_decision(
        self,
        trace_id: str,
        stage: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        reasoning: str = "",
    ) -> None:
        """Record a decision point with human-readable reasoning."""
        trace = self._traces.get(trace_id)
        if trace is None:
            return
        if len(trace.events) >= MAX_TRACE_EVENTS:
            return
        trace.events.append(
            TraceEvent(
                timestamp=time.time(),
                stage=stage,
                event_type=event_type,
                data=data or {},
                reasoning=reasoning,
            )
        )

    def record_agent_execution(
        self,
        trace_id: str,
        agent_type: str,
        status: str,
        latency_ms: float,
        content_len: int,
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an agent's execution result."""
        data: dict[str, Any] = {
            "agent_type": agent_type,
            "status": status,
            "latency_ms": latency_ms,
            "content_length": content_len,
            "confidence": confidence,
        }
        if metadata:
            data["metadata"] = metadata
        reasoning = "Agent %s %s (耗时 %.0fms, 置信度 %.2f)" % (
            agent_type,
            status,
            latency_ms,
            confidence,
        )
        self.record_decision(trace_id, "AGENT", "agent_result", data, reasoning)

    def record_fusion(
        self,
        trace_id: str,
        source_count: int = 0,
        merged_length: int = 0,
        strategy: str = "concatenation",
        data: dict[str, Any] | None = None,
        reasoning: str = "",
    ) -> None:
        """Record fusion of multi-source evidence."""
        data = data or {}
        data.update(
            {
                "source_count": source_count,
                "merged_context_length": merged_length,
                "strategy": strategy,
            }
        )
        if not reasoning:
            reasoning = "融合了 %d 个来源的证据 (策略: %s，合并后上下文长度 %d)" % (
                source_count,
                strategy,
                merged_length,
            )
        self.record_decision(trace_id, "FUSION", "merge", data, reasoning)

    def record_critic(
        self,
        trace_id: str,
        issues_found: int = 0,
        corrections: list[str] | None = None,
        llm_feedback: str = "",
    ) -> None:
        """Record critic review results."""
        data: dict[str, Any] = {"issues_found": issues_found, "corrections": corrections or []}
        if llm_feedback:
            data["llm_feedback"] = llm_feedback
        reasoning = "Critic 审查发现 %d 个问题" % issues_found
        self.record_decision(trace_id, "CRITIC", "review", data, reasoning)

    def record_rewrite(
        self,
        trace_id: str,
        iteration: int = 0,
        reason: str = "",
        improvement: str = "",
        data: dict[str, Any] | None = None,
        reasoning: str = "",
    ) -> None:
        """Record a rewrite iteration."""
        data = data or {}
        data["iteration"] = iteration
        data["reason"] = reason
        reasoning = reasoning or ("第 %d 次重写" % iteration)
        self.record_decision(trace_id, "REWRITE", "correction", data, reasoning)

    def record_final(
        self,
        trace_id: str,
        answer_length: int = 0,
        confidence: float = 0.0,
        total_agents: int = 0,
        total_latency_ms: float = 0.0,
        data: dict[str, Any] | None = None,
        reasoning: str = "",
    ) -> None:
        """Record the final answer."""
        data = data or {}
        data.update(
            {
                "answer_length": answer_length,
                "confidence": confidence,
                "total_agents_executed": total_agents,
                "total_latency_ms": total_latency_ms,
            }
        )
        reasoning = reasoning or (
            "最终回答生成 (%d 字符, 置信度 %.2f, %d 个 Agent, 总耗时 %.0fms)"
            % (answer_length, confidence, total_agents, total_latency_ms)
        )
        self.record_decision(trace_id, "FINAL", "completion", data, reasoning)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Return a full trace as a serializable dict."""
        trace = self._traces.get(trace_id)
        if trace is None:
            return None
        return self._serialize_trace(trace)

    def list_traces(
        self, session_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List recent traces, optionally filtered by session_id."""
        results: list[dict[str, Any]] = []
        for trace in reversed(self._traces.values()):
            if session_id and trace.session_id != session_id:
                continue
            results.append(
                {
                    "trace_id": trace.trace_id,
                    "session_id": trace.session_id,
                    "query": trace.query,
                    "user_id": trace.user_id,
                    "started_at": trace.started_at,
                    "finished_at": trace.finished_at,
                    "event_count": len(trace.events),
                    "summary": trace.summary,
                }
            )
            if len(results) >= limit:
                break
        return results

    def get_recent_trace_for_session(
        self, session_id: str
    ) -> dict[str, Any] | None:
        """Get the most recent trace for a session."""
        for trace in reversed(self._traces.values()):
            if trace.session_id == session_id:
                return self._serialize_trace(trace)
        return None

    def _serialize_trace(self, trace: CognitiveTrace) -> dict[str, Any]:
        elapsed_ms = (
            int((trace.finished_at - trace.started_at) * 1000)
            if trace.finished_at
            else 0
        )
        return {
            "trace_id": trace.trace_id,
            "session_id": trace.session_id,
            "query": trace.query,
            "user_id": trace.user_id,
            "started_at": trace.started_at,
            "finished_at": trace.finished_at,
            "elapsed_ms": elapsed_ms,
            "event_count": len(trace.events),
            "pipeline_stages": self._build_stage_summary(trace),
            "events": [
                {
                    "timestamp": e.timestamp,
                    "stage": e.stage,
                    "event_type": e.event_type,
                    "data": e.data,
                    "reasoning": e.reasoning,
                }
                for e in trace.events
            ],
            "summary": trace.summary,
            "metadata": trace.metadata,
        }

    @staticmethod
    def _build_stage_summary(trace: CognitiveTrace) -> dict[str, int]:
        stages: dict[str, int] = {}
        e: TraceEvent
        for e in trace.events:
            stages[e.stage] = stages.get(e.stage, 0) + 1
        return stages

    def _evict_if_needed(self) -> None:
        while len(self._traces) > self._max_traces:
            self._traces.popitem(last=False)


_tracer: CognitiveTracer | None = None


def get_cognitive_tracer() -> CognitiveTracer:
    global _tracer
    if _tracer is None:
        _tracer = CognitiveTracer()
    return _tracer
