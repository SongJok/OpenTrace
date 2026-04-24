"""
Working Memory — short-term in-process store for an active agent session.
Holds the current conversation turns + scratchpad variables.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional


IDENTITY_CACHE_KEY = "identity_answer"
_SESSION_WORKING_MEMORIES: dict[str, "WorkingMemory"] = {}


@dataclass
class MemoryEntry:
    role: str           # user | assistant | system | tool
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkingMemory:
    """
    Ring-buffer conversation window + key-value scratchpad.

    Parameters
    ----------
    max_turns : max conversation turns retained in the window
    """

    def __init__(self, max_turns: int = 32) -> None:
        self._turns: deque[MemoryEntry] = deque(maxlen=max_turns)
        self._scratchpad: dict[str, Any] = {}
        self._session_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------
    def bind_session(self, session_id: str) -> None:
        self._session_id = session_id

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    # ------------------------------------------------------------------
    # Conversation turns
    # ------------------------------------------------------------------
    def add_turn(self, role: str, content: str, **metadata) -> None:
        self._turns.append(
            MemoryEntry(role=role, content=content, metadata=metadata)
        )

    def get_turns(self, last_n: Optional[int] = None) -> list[MemoryEntry]:
        turns = list(self._turns)
        if last_n:
            return turns[-last_n:]
        return turns

    def to_messages(self) -> list[dict[str, str]]:
        """Return turns as OpenAI-style message dicts."""
        return [{"role": t.role, "content": t.content} for t in self._turns]

    def clear_turns(self) -> None:
        self._turns.clear()

    # ------------------------------------------------------------------
    # Scratchpad
    # ------------------------------------------------------------------
    def set(self, key: str, value: Any) -> None:
        self._scratchpad[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._scratchpad.get(key, default)

    def delete(self, key: str) -> None:
        self._scratchpad.pop(key, None)

    def clear_scratchpad(self) -> None:
        self._scratchpad.clear()

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self._session_id,
            "turns": [
                {"role": t.role, "content": t.content, "ts": t.timestamp}
                for t in self._turns
            ],
            "scratchpad": dict(self._scratchpad),
        }


def get_or_create_session_memory(session_id: str, max_turns: int = 32) -> WorkingMemory:
    if not session_id:
        raise ValueError("session_id is required for session working memory")

    memory = _SESSION_WORKING_MEMORIES.get(session_id)
    if memory is None:
        memory = WorkingMemory(max_turns=max_turns)
        memory.bind_session(session_id)
        _SESSION_WORKING_MEMORIES[session_id] = memory
    return memory


def get_cached_identity_answer(session_id: str) -> Optional[str]:
    if not session_id:
        return None

    memory = _SESSION_WORKING_MEMORIES.get(session_id)
    if memory is None:
        return None
    cached = memory.get(IDENTITY_CACHE_KEY)
    return str(cached) if isinstance(cached, str) and cached else None


def cache_identity_answer(session_id: str, query: str, answer: str) -> None:
    if not session_id or not answer:
        return

    memory = get_or_create_session_memory(session_id)
    if query:
        memory.add_turn("user", query, topic="identity")
    memory.add_turn("assistant", answer, topic="identity")
    memory.set(IDENTITY_CACHE_KEY, answer)


def clear_session_memory(session_id: str) -> None:
    if session_id:
        _SESSION_WORKING_MEMORIES.pop(session_id, None)
