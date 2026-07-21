"""Memory write / salience policy — canonical."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryPolicyDecision:
    allow_write: bool = True
    max_tokens: int = 4096
    violations: list[str] = field(default_factory=list)


class MemoryPolicyEngine:
    def evaluate_write(
        self,
        *,
        proposed_tokens: int,
        pollution_risk: float = 0.0,
    ) -> MemoryPolicyDecision:
        violations: list[str] = []
        if proposed_tokens > 8000:
            violations.append("memory_write_too_large")
        if pollution_risk > 0.7:
            violations.append("memory_pollution_risk")
        return MemoryPolicyDecision(
            allow_write=len(violations) == 0,
            max_tokens=min(4096, proposed_tokens or 4096),
            violations=violations,
        )