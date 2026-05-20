"""Stub: Semantic Cache — V5 routing feature not yet implemented."""

from __future__ import annotations

from dataclasses import dataclass, field

from infra.observability.logger import get_logger

logger = get_logger(__name__)
_WARNED = False


@dataclass
class CacheEntry:
    answer: str | None = None
    content: str | None = None


class SemanticCache:
    async def lookup(
        self, query: str, ctx_hash: str = ""
    ) -> CacheEntry | None:
        global _WARNED
        if not _WARNED:
            logger.warning(
                "SemanticCache is a stub — V5 routing feature not yet implemented"
            )
            _WARNED = True
        return None

    async def store(
        self, query: str, content: str, ctx_hash: str = ""
    ) -> None:
        pass
