"""
运行时快照 — 在关键决策点捕获完整的 RuntimeContext。

在管线每个阶段边界捕获 RuntimeContext、CognitivePlan、ExecutionPlan
和证据的完整状态。支持时间点回放和认知决策调试。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RuntimeSnapshot:
    """决策点处运行时状态的完整快照。"""
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    phase: str = ""  # "pre_rewrite" | "post_understanding" | "post_planning" | "post_execution" | "post_fusion"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    request_id: str = ""
    session_id: str = ""

    # 此时刻的运行时上下文
    query: str = ""
    rewritten_query: str = ""
    conversation_turn: int = 0

    # 认知状态
    understanding_summary: dict[str, Any] = field(default_factory=dict)
    cognitive_plan_summary: dict[str, Any] = field(default_factory=dict)
    execution_plan_summary: dict[str, Any] = field(default_factory=dict)

    # 证据状态
    evidence_count: int = 0
    evidence_summary: dict[str, int] = field(default_factory=dict)  # source → count

    # 指标
    total_latency_ms: int = 0
    total_tokens: int = 0
    error: str = ""


class RuntimeSnapshotStore:
    """运行时快照的内存存储。

    在每个管线阶段捕获运行时状态用于调试和回放。
    """

    def __init__(self, max_per_session: int = 20) -> None:
        self._snapshots: list[RuntimeSnapshot] = []
        self._by_session: dict[str, list[RuntimeSnapshot]] = {}
        self.max_per_session = max_per_session

    def capture(
        self,
        phase: str,
        request_id: str = "",
        session_id: str = "",
        query: str = "",
        rewritten_query: str = "",
        conversation_turn: int = 0,
        understanding_summary: dict[str, Any] | None = None,
        cognitive_plan_summary: dict[str, Any] | None = None,
        execution_plan_summary: dict[str, Any] | None = None,
        evidence_count: int = 0,
        evidence_summary: dict[str, int] | None = None,
        total_latency_ms: int = 0,
        total_tokens: int = 0,
        error: str = "",
    ) -> RuntimeSnapshot:
        """捕获当前运行时状态。"""
        snapshot = RuntimeSnapshot(
            phase=phase,
            request_id=request_id,
            session_id=session_id,
            query=query,
            rewritten_query=rewritten_query,
            conversation_turn=conversation_turn,
            understanding_summary=understanding_summary or {},
            cognitive_plan_summary=cognitive_plan_summary or {},
            execution_plan_summary=execution_plan_summary or {},
            evidence_count=evidence_count,
            evidence_summary=evidence_summary or {},
            total_latency_ms=total_latency_ms,
            total_tokens=total_tokens,
            error=error,
        )
        self._snapshots.append(snapshot)

        if session_id:
            session_snaps = self._by_session.setdefault(session_id, [])
            session_snaps.append(snapshot)
            if len(session_snaps) > self.max_per_session:
                session_snaps.pop(0)

        return snapshot

    def get_by_session(self, session_id: str) -> list[RuntimeSnapshot]:
        return list(self._by_session.get(session_id, []))

    def get_by_phase(self, phase: str, session_id: str) -> list[RuntimeSnapshot]:
        return [
            s for s in self.get_by_session(session_id)
            if s.phase == phase
        ]

    def get_timeline(self, session_id: str) -> list[dict[str, Any]]:
        """返回会话所有阶段的时间线。"""
        snaps = sorted(
            self.get_by_session(session_id),
            key=lambda s: s.timestamp,
        )
        return [
            {
                "phase": s.phase,
                "timestamp": s.timestamp,
                "evidence_count": s.evidence_count,
                "total_tokens": s.total_tokens,
                "error": s.error,
            }
            for s in snaps
        ]

    def clear_session(self, session_id: str) -> None:
        self._by_session.pop(session_id, None)


# 模块级单例
runtime_snapshot_store = RuntimeSnapshotStore()
