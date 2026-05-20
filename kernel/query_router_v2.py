"""Stub: L0 Rule Router — V5 routing feature not yet implemented."""

from __future__ import annotations

from dataclasses import dataclass, field

from infra.observability.logger import get_logger

logger = get_logger(__name__)
_WARNED = False


@dataclass
class L0RouteResult:
    hit: bool = False
    answer: str | None = None
    route: str = "v4"


class L0RuleRouter:
    async def route(
        self,
        query: str,
        session_id: str = "",
        is_multi: bool = False,
        conversation_history: list | None = None,
    ) -> L0RouteResult:
        global _WARNED
        if not _WARNED:
            logger.warning(
                "L0RuleRouter is a stub — V5 routing feature not yet implemented"
            )
            _WARNED = True
        return L0RouteResult()
