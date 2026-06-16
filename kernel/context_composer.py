"""桩：上下文编排器 — V5 能力尚未实现。"""

from __future__ import annotations

from infra.observability.logger import get_logger

logger = get_logger(__name__)
_WARNED = False


class ContextComposer:
    def __init__(self) -> None:
        global _WARNED
        if not _WARNED:
            logger.warning(
                "ContextComposer is a stub — V5 context composer feature not yet implemented"
            )
            _WARNED = True
