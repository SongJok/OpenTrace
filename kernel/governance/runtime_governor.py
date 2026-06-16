"""运行时治理 — 预算、阶段限制与契约合规。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.protocol.governance import Budget, BudgetTracker
from kernel.protocol.runtime_contract import RuntimeTask


@dataclass
class RuntimeGovernanceResult:
    allowed: bool = True
    reason: str = ""
    violations: list[str] = field(default_factory=list)


class RuntimeGovernor:
    def __init__(self, budget: Budget | None = None) -> None:
        self._tracker = BudgetTracker(budget)

    def evaluate_task(self, task: RuntimeTask) -> RuntimeGovernanceResult:
        violations: list[str] = []
        if not task.id:
            violations.append("missing_task_id")
        if not task.goal or not task.goal.description:
            violations.append("missing_goal")
        if self._tracker.is_exhausted():
            violations.append("budget_exhausted")
        return RuntimeGovernanceResult(
            allowed=len(violations) == 0,
            reason="ok" if not violations else ";".join(violations),
            violations=violations,
        )

    def record_step(self, tokens: int = 0, llm_calls: int = 0) -> None:
        self._tracker.record(tokens=tokens, steps=1, llm_calls=llm_calls)