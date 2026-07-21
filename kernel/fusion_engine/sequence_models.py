from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PerQuestionResult:
    sub_question_id: str = ""
    question_text: str = ""
    display_order: int = 0
    answer: str = ""
    success: bool = True
    status: str = "ok"
    error_reason: str = ""
    source: str = "general_qa"
    confidence: float = 0.0
    result_refs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SequenceFusionInput:
    query: str = ""
    sub_questions: list[dict[str, Any]] = field(default_factory=list)
    agent_results: list[Any] = field(default_factory=list)
    background_materials: str = ""


@dataclass
class SequenceFusionOutput:
    content: str = ""
    per_question_results: list[PerQuestionResult] = field(default_factory=list)
    confidence: float = 0.0
    result_refs: list[dict[str, Any]] = field(default_factory=list)
