"""运行时策略引擎 — 执行前治理（规划、路由、能力选择）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.protocol.runtime_contract import RuntimeTask


@dataclass
class RuntimePolicyDecision:
    allowed: bool = True
    violations: list[str] = field(default_factory=list)
    guardrails: dict[str, Any] = field(default_factory=dict)


class RuntimePolicyEngine:
    """Front-load policy before execution projection and capability dispatch."""

    def evaluate_planning_phase(
        self, task: RuntimeTask, *, sub_goal_count: int = 0
    ) -> RuntimePolicyDecision:
        from kernel.governance.cognitive_policy_engine import CognitivePolicyEngine

        intent = task.goal_graph.intent_category if task.goal_graph else "general"
        cog = CognitivePolicyEngine().evaluate_planning(
            intent_category=intent,
            sub_goal_count=sub_goal_count,
            max_steps=task.budget.max_steps,
            allowed_capabilities=task.constraints.allowed_capabilities,
        )
        base = self.evaluate_pre_execution(task)
        violations = list(base.violations) + list(cog.violations)
        guardrails = dict(base.guardrails)
        guardrails["max_capabilities"] = cog.max_capabilities
        return RuntimePolicyDecision(
            allowed=len(violations) == 0,
            violations=violations,
            guardrails=guardrails,
        )

    def evaluate_pre_execution(self, task: RuntimeTask, ctx: Any = None) -> RuntimePolicyDecision:
        violations: list[str] = []
        if not (task.goal.description or "").strip():
            violations.append("missing_goal")
        if task.budget.max_steps < 1:
            violations.append("invalid_budget_steps")
        disallowed = set(task.constraints.disallowed_capabilities or [])
        allowed = set(task.constraints.allowed_capabilities or [])
        if allowed and disallowed & allowed:
            violations.append("capability_allow_deny_conflict")
        return RuntimePolicyDecision(
            allowed=len(violations) == 0,
            violations=violations,
            guardrails={
                "max_parallel": task.constraints.max_parallel,
                "relevance_threshold": task.constraints.relevance_threshold,
            },
        )