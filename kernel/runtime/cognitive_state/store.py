"""会话级运行时认知状态（单回合内跨阶段演化）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CognitiveRuntimeState:
    request_id: str
    session_id: str
    goal_id: str = ""
    phase: str = "init"
    reasoning_notes: list[str] = field(default_factory=list)
    world_state_snapshot: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    memory_bindings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def advance_phase(self, phase: str, note: str = "") -> None:
        self.phase = phase
        if note:
            self.reasoning_notes.append(f"{phase}:{note}")


_STATE: dict[str, CognitiveRuntimeState] = {}


def get_or_create_runtime_state(
    request_id: str,
    session_id: str,
    goal_id: str = "",
) -> CognitiveRuntimeState:
    key = f"{session_id}:{request_id}"
    if key not in _STATE:
        _STATE[key] = CognitiveRuntimeState(
            request_id=request_id,
            session_id=session_id,
            goal_id=goal_id,
        )
    return _STATE[key]