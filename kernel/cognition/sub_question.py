"""子问题分解类型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubQuestion:
    question: str = ""
    answer: str = ""
    confidence: float = 0.0
    sub_questions: list[SubQuestion] = field(default_factory=list)
