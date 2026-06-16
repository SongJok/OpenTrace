"""桩：回合上下文 — V5 能力尚未实现。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TurnContext:
    query: str = ""
    session_id: str = ""
    user_id: str = ""
    recent_history: list | None = None
    memory_context: list | None = None
    attachment_contexts: list | None = None
    conversation_state: dict | None = None
    metadata: dict | None = None
