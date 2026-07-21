"""Optional Redis persistence for cognitive runtime state (phase 2)."""

from __future__ import annotations

import json
from typing import Any

from infra.observability.logger import get_logger
from kernel.runtime.cognitive_state.store import CognitiveRuntimeState

logger = get_logger(__name__)


def _redis_key(session_id: str, request_id: str) -> str:
    return f"cog_state:{session_id}:{request_id}"


def _graph_redis_key(session_id: str, request_id: str) -> str:
    return f"cog_state_graph:{session_id}:{request_id}"


def _graph_persist_enabled() -> bool:
    from infra.config.settings import settings

    if bool(getattr(settings, "kernel_cognitive_state_graph_persist_enabled", False)):
        return True
    # Production profile may enable graph persist via cognitive_state_persist
    return bool(getattr(settings, "kernel_cognitive_state_persist_enabled", False))


async def flush_cognitive_state_graph(graph: Any) -> None:
    """Persist CognitiveStateGraph JSON when graph persist flag is on."""
    try:
        if not _graph_persist_enabled():
            return
        from infra.cache.redis_client import get_memory_redis

        sid = str(getattr(graph, "session_id", "") or "")
        rid = str(getattr(graph, "request_id", "") or "")
        if not sid or not rid:
            return
        r = await get_memory_redis()
        payload = graph.model_dump(mode="json")
        from infra.config.settings import settings

        ttl = int(getattr(settings, "kernel_cognitive_state_graph_ttl_seconds", 3600))
        await r.setex(
            _graph_redis_key(sid, rid),
            ttl,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception as exc:
        logger.warning("cognitive_state_graph_flush_skipped", error=str(exc))


async def load_cognitive_state_graph(
    session_id: str, request_id: str
) -> dict[str, Any] | None:
    try:
        if not _graph_persist_enabled():
            return None
        from infra.cache.redis_client import get_memory_redis

        r = await get_memory_redis()
        raw = await r.get(_graph_redis_key(session_id, request_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


async def flush_runtime_state(state: CognitiveRuntimeState) -> None:
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_cognitive_state_persist_enabled", False)):
            return
        from infra.cache.redis_client import get_memory_redis

        r = await get_memory_redis()
        payload = {
            "phase": state.phase,
            "goal_id": state.goal_id,
            "evidence_ids": list(state.evidence_ids),
            "world_state_snapshot": dict(state.world_state_snapshot),
            "metrics": dict(state.metrics),
        }
        await r.setex(
            _redis_key(state.session_id, state.request_id),
            3600,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception as exc:
        logger.warning("cognitive_state_flush_skipped", error=str(exc))


async def load_runtime_state(
    session_id: str, request_id: str
) -> dict[str, Any] | None:
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_cognitive_state_persist_enabled", False)):
            return None
        from infra.cache.redis_client import get_memory_redis

        r = await get_memory_redis()
        raw = await r.get(_redis_key(session_id, request_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None