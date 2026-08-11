"""可版本化的内置分析技能。

技能只声明分析方法和验证前置条件，不携带凭证，也不允许绕过 SQLGuard。
"""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.contracts import LogicalQueryPlan


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    intent: str
    version: str
    required_inputs: tuple[str, ...]
    validation_rules: tuple[str, ...]


BUILTIN_SKILLS: tuple[SkillDefinition, ...] = (
    SkillDefinition(
        "aggregation", "aggregation", "1.0", ("metric",), ("metric_contract", "group_by")
    ),
    SkillDefinition(
        "time_series", "trend", "1.0", ("metric", "time_window"), ("time_column", "order_by")
    ),
    SkillDefinition("ranking", "ranking", "1.0", ("metric",), ("order_by", "limit")),
    SkillDefinition("funnel", "funnel", "1.0", ("events",), ("ordered_steps", "denominator")),
    SkillDefinition(
        "cohort", "cohort", "1.0", ("entity", "time_window"), ("cohort_key", "retention_grain")
    ),
    SkillDefinition("lookup", "lookup", "1.0", ("entity",), ("stable_order", "limit")),
)


class SkillRegistry:
    def select(self, plan: LogicalQueryPlan) -> SkillDefinition:
        return next(
            (item for item in BUILTIN_SKILLS if item.intent == plan.intent),
            next(item for item in BUILTIN_SKILLS if item.intent == "lookup"),
        )

    def enrich(self, plan: LogicalQueryPlan) -> LogicalQueryPlan:
        skill = self.select(plan)
        assumptions = list(plan.assumptions)
        assumptions.append(f"使用分析技能 {skill.name} v{skill.version}")
        return plan.model_copy(update={"assumptions": assumptions})
