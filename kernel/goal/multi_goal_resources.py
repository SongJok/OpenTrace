"""Multi-goal resource competition and budget projection."""

from __future__ import annotations

from typing import Any

from kernel.protocol.runtime_contract import Goal, GoalGraph


def project_multi_goal_resource_plan(
    goal_graph: GoalGraph,
    *,
    max_parallel_sub_goals: int = 3,
    cognitive_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compute priority ordering, parallelism cap, and per-goal resource slots.
    """
    budget = dict(cognitive_budget or {})
    max_cap = int(budget.get("max_capabilities", 3) or 3)
    max_parallel = min(max_parallel_sub_goals, max(1, max_cap))

    root_id = goal_graph.root_goal_id
    children: list[Goal] = [
        g
        for g in goal_graph.goals
        if g.parent_id == root_id and g.goal_id != root_id
    ]
    children.sort(key=lambda g: (g.priority, g.goal_id))

    slots: list[dict[str, Any]] = []
    for i, g in enumerate(children):
        slots.append(
            {
                "goal_id": g.goal_id,
                "priority": g.priority,
                "wave": i // max_parallel,
                "slot_index": i % max_parallel,
                "competes_with": [
                    c.goal_id
                    for c in children
                    if c.goal_id != g.goal_id
                    and (c.priority // max_parallel) == (g.priority // max_parallel)
                ][:8],
            }
        )

    parallel_eligible = len(children) <= max_parallel and all(
        not (g.metadata or {}).get("requires_sequential") for g in children
    )
    return {
        "sub_goal_count": len(children),
        "max_parallel_sub_goals": max_parallel,
        "parallel_eligible": parallel_eligible,
        "resource_slots": slots,
        "sequential_required": not parallel_eligible,
    }