"""
提示词快照 — 捕获每次 LLM 提示词 + 响应用于审计和回放。

认知管线中的每次 LLM 调用都会产生一个快照，包括：
- 完整系统提示词
- 完整用户提示词
- 模型响应
- 模型角色 + 参数（temperature、max_tokens）
- 时间戳和追踪上下文

这些快照支持确定性回放和合规审计。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PromptSnapshot:
    """一次 LLM 调用的不可变记录。"""
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    phase: str = ""               # "rewrite" | "understanding" | "planning" | "fusion" | "critic"
    model_role: str = ""           # LLMRole 值：QUERY、PLANNING、CHEAP_CRITIC 等
    model_name: str = ""           # 实际使用的模型
    system_prompt: str = ""
    user_prompt: str = ""
    response: str = ""
    temperature: float = 0.0
    max_tokens: int = 800
    latency_ms: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)  # {prompt_tokens, completion_tokens}
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    request_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    error: str = ""


class PromptSnapshotStore:
    """线程安全的内存提示词快照存储。

    在生产环境中，这些应持久化到专用审计表。
    存储保留每个会话最近 N 个快照用于调试。
    """

    def __init__(self, max_per_session: int = 50) -> None:
        self._snapshots: list[PromptSnapshot] = []
        self._by_session: dict[str, list[PromptSnapshot]] = {}
        self.max_per_session = max_per_session

    def record(
        self,
        phase: str,
        model_role: str,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        temperature: float = 0.0,
        max_tokens: int = 800,
        latency_ms: int = 0,
        token_usage: dict[str, int] | None = None,
        request_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        error: str = "",
    ) -> PromptSnapshot:
        """记录一对提示词/响应。"""
        snapshot = PromptSnapshot(
            phase=phase,
            model_role=model_role,
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response,
            temperature=temperature,
            max_tokens=max_tokens,
            latency_ms=latency_ms,
            token_usage=token_usage or {},
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            error=error,
        )
        self._snapshots.append(snapshot)

        if session_id:
            session_snaps = self._by_session.setdefault(session_id, [])
            session_snaps.append(snapshot)
            if len(session_snaps) > self.max_per_session:
                session_snaps.pop(0)

        return snapshot

    def get_by_session(self, session_id: str) -> list[PromptSnapshot]:
        return list(self._by_session.get(session_id, []))

    def get_by_phase(self, phase: str, session_id: str = "") -> list[PromptSnapshot]:
        snaps = self.get_by_session(session_id) if session_id else self._snapshots
        return [s for s in snaps if s.phase == phase]

    def get_recent(self, n: int = 20) -> list[PromptSnapshot]:
        return self._snapshots[-n:]

    def get_latest(self) -> PromptSnapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    @property
    def total_snapshots(self) -> int:
        return len(self._snapshots)

    def clear_session(self, session_id: str) -> None:
        self._by_session.pop(session_id, None)


# 模块级单例
prompt_snapshot_store = PromptSnapshotStore()
