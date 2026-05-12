from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CriticInput:
    query: str
    answer: str
    fusion_context: str
    fusion_confidence: float
    adaptive_profile: dict[str, object] | None = None
    # Optional: multiple candidate answers from different agents
    candidate_answers: list[dict[str, object]] = field(default_factory=list)


@dataclass
class CandidateScore:
    """Decomposed score for a single candidate answer."""
    answer: str
    source: str = ""
    factual_consistency: float = 0.0
    relevance: float = 0.0
    completeness: float = 0.0
    coherence: float = 0.0

    @property
    def composite(self) -> float:
        """Weighted composite score."""
        return (
            0.35 * self.factual_consistency
            + 0.30 * self.relevance
            + 0.20 * self.completeness
            + 0.15 * self.coherence
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "composite": round(self.composite, 3),
            "factual_consistency": round(self.factual_consistency, 3),
            "relevance": round(self.relevance, 3),
            "completeness": round(self.completeness, 3),
            "coherence": round(self.coherence, 3),
            "answer_snippet": self.answer[:200],
        }


@dataclass
class CriticOutput:
    need_fix: bool
    feedback: str
    improved_answer: str = ""
    # Explainable confidence
    confidence_breakdown: dict[str, float] = field(default_factory=dict)
    confidence_explanation: str = ""
    # Multi-candidate scores when available
    candidate_scores: list[CandidateScore] = field(default_factory=list)
    selected_candidate_index: int = -1
