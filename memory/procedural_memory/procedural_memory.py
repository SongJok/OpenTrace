"""
Procedural Memory — stores how-to knowledge (action patterns, workflows).
Backed by Redis hashes for fast lookup by procedure name.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from infra.cache.redis_client import get_memory_redis
from infra.observability.logger import get_logger

logger = get_logger(__name__)

PROC_KEY = "opentrace:procedural:{name}"
PROC_INDEX_KEY = "opentrace:procedural:index"


class ProceduralMemory:
    """
    Key-value store for reusable procedure descriptions and templates.
    """

    async def store(
        self,
        name: str,
        description: str,
        steps: list[str],
        tags: Optional[list[str]] = None,
    ) -> None:
        r = await get_memory_redis()
        payload = json.dumps({
            "name": name,
            "description": description,
            "steps": steps,
            "tags": tags or [],
            "updated": time.time(),
        })
        key = PROC_KEY.format(name=name)
        await r.set(key, payload)
        await r.sadd(PROC_INDEX_KEY, name)
        logger.debug("Procedure stored", name=name)

    async def retrieve(self, name: str) -> Optional[dict[str, Any]]:
        r = await get_memory_redis()
        raw = await r.get(PROC_KEY.format(name=name))
        if raw:
            return json.loads(raw)
        return None

    async def list_procedures(self) -> list[str]:
        r = await get_memory_redis()
        members = await r.smembers(PROC_INDEX_KEY)
        return list(members)

    async def delete(self, name: str) -> None:
        r = await get_memory_redis()
        await r.delete(PROC_KEY.format(name=name))
        await r.srem(PROC_INDEX_KEY, name)
