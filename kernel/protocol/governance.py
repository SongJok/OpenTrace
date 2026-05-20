"""Governance protocol types — budget tracking, quality gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Budget:
    max_tokens: int = 10000
    max_steps: int = 10
    max_llm_calls: int = 5
    max_time_seconds: float = 30.0

    def is_exceeded(self, tokens: int = 0, steps: int = 0, llm_calls: int = 0) -> bool:
        return (tokens > self.max_tokens or steps > self.max_steps or llm_calls > self.max_llm_calls)


class BudgetTracker:
    def __init__(self, budget: Budget | None = None):
        self.budget = budget or Budget()
        self.tokens_used = 0
        self.steps_taken = 0
        self.llm_calls_made = 0

    def record(self, tokens: int = 0, steps: int = 1, llm_calls: int = 0) -> None:
        self.tokens_used += tokens
        self.steps_taken += steps
        self.llm_calls_made += llm_calls

    def is_exhausted(self) -> bool:
        return self.budget.is_exceeded(self.tokens_used, self.steps_taken, self.llm_calls_made)


@dataclass
class GovernanceProfile:
    name: str = "default"
    budget: Budget = field(default_factory=Budget)
    allow_fallbacks: bool = True


@dataclass
class QualityGate:
    min_confidence: float = 0.5
    min_evidence_count: int = 1
    require_citation: bool = False


@dataclass
class QualityGateResult:
    passed: bool = True
    score: float = 1.0
    failures: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
