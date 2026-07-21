"""Cognitive plan + strategy build — separated from execution projection."""

from __future__ import annotations

from typing import Any


async def build_cognitive_plan_and_strategy(
    canonical_query: str,
    ctx: Any,
    understanding: Any = None,
) -> tuple[Any, Any]:
    from kernel.runtime.cognitive.cognitive_planner_v2 import CognitivePlannerV2
    from kernel.runtime.cognitive.strategy_builder import StrategyBuilder
    from kernel.runtime.capability import capability_registry

    cognitive_plan = await CognitivePlannerV2(capability_registry=capability_registry).plan(
        canonical_query, ctx, understanding=understanding
    )
    strategy = StrategyBuilder(capability_registry=capability_registry).build(cognitive_plan)
    return cognitive_plan, strategy