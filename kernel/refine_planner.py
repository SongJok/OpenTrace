"""Refine planner stub — incremental re-planning for corrections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CorrectionIntent:
    is_correction: bool = False
    confidence: float = 0.0
    corrected_query: str = ""


@dataclass
class RefinedPlan:
    plan: Any = None
    reused_results: dict = field(default_factory=dict)
    replaced_indices: list[int] = field(default_factory=list)


class RefinePlanner:

    async def detect_correction(
        self, query: str, previous_plan: Any
    ) -> CorrectionIntent:
        return CorrectionIntent()

    def refine_plan(
        self,
        correction_intent: CorrectionIntent,
        previous_plan: Any,
        previous_results: Any,
        query: str,
    ) -> RefinedPlan:
        return RefinedPlan()
