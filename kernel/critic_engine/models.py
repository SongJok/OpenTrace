from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CriticInput:
    query: str
    answer: str
    fusion_context: str
    fusion_confidence: float
    adaptive_profile: dict[str, object] | None = None


@dataclass
class CriticOutput:
    need_fix: bool
    feedback: str
    improved_answer: str = ""
