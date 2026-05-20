"""Stub: Tiny Router — V5 routing feature not yet implemented."""

from __future__ import annotations

from dataclasses import dataclass, field

from infra.observability.logger import get_logger

logger = get_logger(__name__)
_WARNED = False


@dataclass
class L1RouteResult:
    route: str = "v4"
    answer: str | None = None


class TinyRouter:
    async def route(
        self, query: str, history: list | None = None
    ) -> L1RouteResult:
        global _WARNED
        if not _WARNED:
            logger.warning(
                "TinyRouter is a stub — V5 routing feature not yet implemented"
            )
            _WARNED = True
        return L1RouteResult()
