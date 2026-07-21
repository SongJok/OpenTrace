"""Cognitive-phase policy (planning, capability selection hints) — canonical."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CognitivePolicyDecision:
    allowed: bool = True
    violations: list[str] = field(default_factory=list)
    max_capabilities: int = 5


class CognitivePolicyEngine:
    def evaluate_planning(
        self,
        *,
        intent_category: str,
        sub_goal_count: int,
        max_steps: int,
        allowed_capabilities: list[str] | None = None,
    ) -> CognitivePolicyDecision:
        violations: list[str] = []
        if max_steps < 1:
            violations.append("plan_steps_zero")
        if sub_goal_count > 8:
            violations.append("too_many_sub_goals")
        cap = 5
        if intent_category == "data_query":
            cap = 3
        return CognitivePolicyDecision(
            allowed=len(violations) == 0,
            violations=violations,
            max_capabilities=cap,
        )