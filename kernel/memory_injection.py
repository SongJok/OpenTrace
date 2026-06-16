"""Unified memory context injection for CognitiveKernel (sync + stream)."""

from __future__ import annotations

import json
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


async def collect_episodic_keyword_chunks(
    session_id: str,
    *,
    user_preferences: list[Any] | None = None,
    preference_context_block: str = "",
) -> tuple[list[str], list[str]]:
    """Episodic (Redis) + working-memory keyword chunks."""
    episodic_chunks: list[str] = []
    keyword_chunks: list[str] = []

    if session_id:
        try:
            from memory.episodic_memory.episodic_memory import EpisodicMemory

            episodic = EpisodicMemory(session_id)
            episodic_events = await episodic.recall(last_n=20)
            for e in episodic_events:
                try:
                    inner = json.loads(e.get("content", "{}"))
                    if isinstance(inner, dict):
                        q = inner.get("q", "")
                        a = inner.get("a", "")
                        if q and a:
                            episodic_chunks.append(f"Q: {q}\nA: {a[:300]}")
                        else:
                            episodic_chunks.append(e.get("content", "")[:500])
                    else:
                        episodic_chunks.append(str(inner)[:500])
                except (json.JSONDecodeError, TypeError):
                    episodic_chunks.append(str(e.get("content", ""))[:500])
        except Exception as exc:
            logger.warning("Episodic memory fetch failed", error=str(exc))

        try:
            from memory.working_memory.working_memory import get_or_create_session_memory

            wm = get_or_create_session_memory(session_id)
            keyword_chunks = [
                f"user: {t.content}" if t.role == "user" else f"assistant: {t.content}"
                for t in wm.get_turns(last_n=8)
            ] + list(user_preferences or [])
            if preference_context_block:
                keyword_chunks.append(preference_context_block)
        except Exception as exc:
            logger.warning("Working memory turns fetch failed", error=str(exc))

    return episodic_chunks, keyword_chunks


async def inject_memory_context_for_turn(
    *,
    session_id: str,
    query: str,
    metadata: dict[str, Any],
    memory_injection_enabled: bool,
    budget_allows_memory: bool,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Fabric-first retrieval merged with legacy router when sparse."""
    if not memory_injection_enabled or not session_id or not budget_allows_memory:
        return []

    episodic, keyword = await collect_episodic_keyword_chunks(
        session_id,
        user_preferences=metadata.get("user_preferences"),
        preference_context_block=str(metadata.get("user_preference_context_block", "") or ""),
    )
    if not episodic and not keyword and not session_id:
        return []

    goal_id = str(
        (metadata.get("goal_graph") or {}).get("root_goal_id", "")
        or metadata.get("request_id", session_id)
    )
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_memory_fabric_retrieval_enabled", True)):
            from memory.fabric.retrieval import merge_fabric_with_legacy_retrieve

            return await merge_fabric_with_legacy_retrieve(
                session_id=session_id,
                goal_id=goal_id,
                query=query,
                episodic_chunks=episodic,
                keyword_chunks=keyword,
                top_k=top_k,
            )
        from memory.memory_router.router import get_memory_router

        memory_chunks = await get_memory_router().retrieve(
            query=query,
            episodic_chunks=episodic,
            keyword_chunks=keyword,
            top_k=top_k,
        )
        return [
            {"content": c.content, "score": c.score, "source": c.source}
            for c in memory_chunks
        ]
    except Exception as exc:
        logger.debug("Memory inject failed", error=str(exc))
        return []