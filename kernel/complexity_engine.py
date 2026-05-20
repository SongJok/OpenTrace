"""Stub: Complexity Engine — V5 routing feature not yet implemented."""

from __future__ import annotations

from dataclasses import dataclass, field

from infra.observability.logger import get_logger

logger = get_logger(__name__)
_WARNED = False


@dataclass
class ComplexityAssessment:
    recommended_pipeline: str = "v4"


class ComplexityEngine:
    def assess(
        self,
        query: str,
        conversation_context: dict | None = None,
    ) -> ComplexityAssessment:
        global _WARNED
        if not _WARNED:
            logger.warning(
                "ComplexityEngine is a stub — V5 routing feature not yet implemented"
            )
            _WARNED = True
        return ComplexityAssessment()
