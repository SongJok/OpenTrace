"""审计治理 — 语义可观测性钩子。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class SemanticObservabilitySnapshot:
    reasoning_quality: float = 1.0
    hallucination_risk: float = 0.0
    evidence_integrity: float = 1.0
    planner_stability: float = 1.0
    strategy_drift: float = 0.0
    capability_entropy: float = 0.0
    memory_pollution: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

class AuditGovernor:
    def capture_turn(
        self,
        *,
        route: str,
        evidence_count: int,
        critic_passed: bool | None,
        hallucination_risk: float,
    ) -> SemanticObservabilitySnapshot:
        integrity = 1.0 if evidence_count > 0 else 0.5
        if critic_passed is False:
            integrity *= 0.5
        return SemanticObservabilitySnapshot(
            hallucination_risk=hallucination_risk,
            evidence_integrity=integrity,
            metadata={"route": route, "evidence_count": evidence_count},
        )