"""Stub: Turn Context — V5 feature not yet implemented."""

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
