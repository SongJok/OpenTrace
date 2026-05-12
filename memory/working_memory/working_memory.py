"""
Working Memory — short-term in-process store for an active agent session.
Holds the current conversation turns + scratchpad variables.
Redis-backed persistence ensures state survives process restarts.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

IDENTITY_CACHE_KEY = "identity_answer"
_SESSION_WORKING_MEMORIES: dict[str, WorkingMemory] = {}

# Redis key namespace
_WM_NS = "wm"
_WM_TTL = 86400  # 24 hours


@dataclass
class MemoryEntry:
    role: str  # user | assistant | system | tool
    content: str | None = None  # nullable for tool-call-only msgs
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkingMemory:
    """
    Ring-buffer conversation window + key-value scratchpad.
    All writes are synchronised to Redis (24h TTL) for cross-restart survival.

    Parameters
    ----------
    max_turns : max conversation turns retained in the window
    session_id : optional session binding for Redis persistence
    """

    def __init__(self, max_turns: int = 32, session_id: str | None = None) -> None:
        self._turns: deque[MemoryEntry] = deque(maxlen=max_turns)
        self._scratchpad: dict[str, Any] = {}
        self._session_id: str | None = session_id

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------
    def bind_session(self, session_id: str) -> None:
        self._session_id = session_id

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _turns_key(session_id: str) -> str:
        return f"{_WM_NS}:{session_id}:turns"

    @staticmethod
    def _scratch_key(session_id: str) -> str:
        return f"{_WM_NS}:{session_id}:scratch"

    async def _sync_to_redis(self) -> None:
        """Write current turns and scratchpad to Redis."""
        if not self._session_id:
            return
        try:
            from infra.cache.redis_client import get_session_redis

            redis = await get_session_redis()
            tkey = self._turns_key(self._session_id)
            skey = self._scratch_key(self._session_id)

            # Write turns as JSON list
            pipe = redis.pipeline()
            pipe.delete(tkey)
            for entry in self._turns:
                pipe.rpush(
                    tkey,
                    json.dumps(
                        {
                            "role": entry.role,
                            "content": entry.content,
                            "tool_calls": entry.tool_calls,
                            "tool_call_id": entry.tool_call_id,
                            "name": entry.name,
                            "ts": entry.timestamp,
                            "meta": entry.metadata,
                        },
                        ensure_ascii=False,
                    ),
                )
            pipe.expire(tkey, _WM_TTL)

            # Write scratchpad as hash (only string-serialisable values)
            pipe.delete(skey)
            for k, v in self._scratchpad.items():
                try:
                    pipe.hset(skey, k, json.dumps(v, ensure_ascii=False, default=str))
                except (TypeError, ValueError):
                    pipe.hset(skey, k, str(v))
            pipe.expire(skey, _WM_TTL)
            await pipe.execute()
        except Exception:
            pass  # Redis persistence is best-effort

    @classmethod
    async def load_from_redis(cls, session_id: str, max_turns: int = 32) -> WorkingMemory:
        """Reconstruct a WorkingMemory from Redis state for the given session."""
        wm = cls(max_turns=max_turns, session_id=session_id)
        try:
            from infra.cache.redis_client import get_session_redis

            redis = await get_session_redis()
            tkey = cls._turns_key(session_id)

            # Load turns from Redis list
            raw_turns = await redis.lrange(tkey, 0, -1)
            for raw in raw_turns or []:
                try:
                    data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                    entry = MemoryEntry(
                        role=data.get("role", "unknown"),
                        content=data.get("content"),
                        tool_calls=data.get("tool_calls"),
                        tool_call_id=data.get("tool_call_id"),
                        name=data.get("name"),
                        timestamp=data.get("ts", time.time()),
                        metadata=data.get("meta", {}),
                    )
                    wm._turns.append(entry)
                except Exception:
                    continue

            # Load scratchpad from Redis hash
            skey = cls._scratch_key(session_id)
            raw_pad = await redis.hgetall(skey)
            if raw_pad:
                for k, v in raw_pad.items():
                    try:
                        wm._scratchpad[k] = json.loads(
                            v if isinstance(v, str) else v.decode("utf-8")
                        )
                    except (json.JSONDecodeError, TypeError):
                        wm._scratchpad[k] = v
        except Exception:
            pass  # Redis unavailable — start fresh
        return wm

    # ------------------------------------------------------------------
    # Conversation turns
    # ------------------------------------------------------------------
    def add_turn(
        self,
        role: str,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
        **metadata,
    ) -> None:
        self._turns.append(
            MemoryEntry(
                role=role,
                content=content,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
                name=name,
                metadata=metadata,
            )
        )
        if self._session_id:
            self._schedule_redis_sync()

    def get_turns(self, last_n: int | None = None) -> list[MemoryEntry]:
        turns = list(self._turns)
        if last_n:
            return turns[-last_n:]
        return turns

    def to_messages(self) -> list[dict[str, Any]]:
        """Return turns as OpenAI-style message dicts with tool_calls support."""
        msgs: list[dict[str, Any]] = []
        for t in self._turns:
            msg: dict[str, Any] = {"role": t.role}
            if t.content is not None:
                msg["content"] = t.content
            if t.tool_calls:
                msg["tool_calls"] = t.tool_calls
            if t.tool_call_id:
                msg["tool_call_id"] = t.tool_call_id
            if t.name:
                msg["name"] = t.name
            msgs.append(msg)
        return msgs

    def clear_turns(self) -> None:
        self._turns.clear()

    # ------------------------------------------------------------------
    # Scratchpad
    # ------------------------------------------------------------------
    def set(self, key: str, value: Any) -> None:
        self._scratchpad[key] = value
        if self._session_id:
            self._schedule_redis_sync()

    def get(self, key: str, default: Any = None) -> Any:
        return self._scratchpad.get(key, default)

    def delete(self, key: str) -> None:
        self._scratchpad.pop(key, None)
        if self._session_id:
            self._schedule_redis_sync()

    def clear_scratchpad(self) -> None:
        self._scratchpad.clear()
        if self._session_id:
            self._schedule_redis_sync()

    def _schedule_redis_sync(self) -> None:
        """Fire-and-forget Redis sync (non-blocking)."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._sync_to_redis())
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self._session_id,
            "turns": [
                {
                    "role": t.role,
                    "content": t.content,
                    "tool_calls": t.tool_calls,
                    "tool_call_id": t.tool_call_id,
                    "name": t.name,
                    "ts": t.timestamp,
                }
                for t in self._turns
            ],
            "scratchpad": dict(self._scratchpad),
        }


def get_or_create_session_memory(session_id: str, max_turns: int = 32) -> WorkingMemory:
    if not session_id:
        raise ValueError("session_id is required for session working memory")

    memory = _SESSION_WORKING_MEMORIES.get(session_id)
    if memory is not None:
        return memory

    # Create a blank one — caller can await load_from_redis for hydrated state.
    memory = WorkingMemory(max_turns=max_turns, session_id=session_id)
    _SESSION_WORKING_MEMORIES[session_id] = memory
    return memory


async def load_or_create_session_memory(session_id: str, max_turns: int = 32) -> WorkingMemory:
    """Get or create session memory, attempting Redis reconstruction first."""
    if not session_id:
        raise ValueError("session_id is required for session working memory")

    memory = _SESSION_WORKING_MEMORIES.get(session_id)
    if memory is not None:
        return memory

    # Try to reconstruct from Redis
    try:
        memory = await WorkingMemory.load_from_redis(session_id, max_turns=max_turns)
    except Exception:
        memory = WorkingMemory(max_turns=max_turns, session_id=session_id)

    _SESSION_WORKING_MEMORIES[session_id] = memory
    return memory


def get_cached_identity_answer(session_id: str) -> str | None:
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
