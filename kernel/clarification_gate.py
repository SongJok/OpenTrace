"""Clarification gate stub — checks if follow-up questions are needed."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClarificationResult:
    needs_clarification: bool = False
    clarification_question: str = ""


class ClarificationGate:

    async def check(
        self,
        fusion_confidence: float = 0.0,
        answer: str = "",
        query: str = "",
    ) -> ClarificationResult:
        return ClarificationResult()
