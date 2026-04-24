"""
Episodic Memory — Redis-backed per-session event store.
Persists significant turns / tool results for cross-session recall.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from infra.cache.redis_client import get_memory_redis
from infra.observability.logger import get_logger
from infra.observability.metrics import MEMORY_HITS

logger = get_logger(__name__)

EPISODE_TTL = 7 * 24 * 3600  # 7 days
EPISODE_KEY = "opentrace:episodic:{session_id}"


class EpisodicMemory:
    """
    Append-only log of significant episodic events per session.
    Backed by a Redis list for persistence across restarts.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._key = EPISODE_KEY.format(session_id=session_id)

    async def record(
        self,
        event_type: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Append an event to the episode log."""
        r = await get_memory_redis()
        entry = json.dumps(
            {
                "type": event_type,
                "content": content,
                "ts": time.time(),
                "meta": metadata or {},
            }
        )
        await r.rpush(self._key, entry)
        await r.expire(self._key, EPISODE_TTL)
        logger.debug("Episode recorded", session=self.session_id, type=event_type)

    async def recall(
        self,
        last_n: int = 20,
        event_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Retrieve the most recent episodic events."""
        r = await get_memory_redis()
        raw = await r.lrange(self._key, -last_n, -1)
        events = [json.loads(e) for e in raw]

        if event_type:
            events = [e for e in events if e.get("type") == event_type]

        MEMORY_HITS.labels(store_type="episodic").inc(len(events))
        return events

    async def clear(self) -> None:
        r = await get_memory_redis()
        await r.delete(self._key)
        logger.info("Episodic memory cleared", session=self.session_id)
