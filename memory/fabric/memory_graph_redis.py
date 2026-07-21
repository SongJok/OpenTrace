"""Optional Redis shadow for session memory graphs (phase 3)."""

from __future__ import annotations

import json
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)

_GRAPH_TTL_SEC = 86400 * 7


def _key(session_id: str) -> str:
    return f"memory_graph:{session_id or 'default'}"


async def persist_graph_snapshot(session_id: str, snapshot: dict[str, Any]) -> None:
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_memory_graph_redis_enabled", False)):
            return
        from infra.cache.redis_client import get_memory_redis

        r = await get_memory_redis()
        await r.setex(_key(session_id), _GRAPH_TTL_SEC, json.dumps(snapshot, ensure_ascii=False))
    except Exception as exc:
        logger.warning(
            "memory_graph_redis_persist_failed",
            session_id=session_id,
            error=str(exc),
        )


async def load_graph_snapshot(session_id: str) -> dict[str, Any] | None:
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_memory_graph_redis_enabled", False)):
            return None
        from infra.cache.redis_client import get_memory_redis

        r = await get_memory_redis()
        raw = await r.get(_key(session_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning(
            "memory_graph_redis_load_failed",
            session_id=session_id,
            error=str(exc),
        )
        return None