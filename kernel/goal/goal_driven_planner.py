"""
Goal-driven planning orchestration — GoalGraph is the primary input to execution projection.

Flow:
  GoalGraph (ctx) → strategic hints → cognitive plan → strategy → projection → goal_id on subtasks
"""

from __future__ import annotations

from typing import Any


async def plan_from_goal_context(
    canonical_query: str,
    ctx: Any,
    understanding: Any = None,
) -> tuple[Any, Any, Any]:
    """Return (cognitive_plan, execution_plan, execution_graph) bound to goal_graph."""
    from infra.config.settings import settings
    from kernel.cognition.planner_facade import ExecutionPlanner, get_strategic_planner
    from kernel.goal.goal_projection import project_goal_graph_to_execution_hints
    from kernel.protocol.runtime_contract import GoalGraph

    md = getattr(ctx, "metadata", None) or {}
    gg_raw = md.get("goal_graph") or {}
    hints = project_goal_graph_to_execution_hints(gg_raw)
    md["goal_execution_projection"] = hints
    ctx.metadata = md

    strategic = get_strategic_planner().project_hints_from_context(ctx, hints)
    md["strategic_plan"] = strategic
    ctx.metadata = md

    root = str(gg_raw.get("root_goal_id", "") or getattr(ctx, "request_id", ""))
    subs = [
        g
        for g in (gg_raw.get("goals") or [])
        if isinstance(g, dict) and g.get("parent_id") == root
    ]

    if bool(getattr(settings, "kernel_goal_driven_dag_enabled", False)) and subs:
        dag = try_build_goal_only_execution_graph(
            canonical_query, ctx, gg_raw, subs, root, understanding=understanding
        )
        if dag is not None:
            cognitive_plan, plan, graph = dag
            return cognitive_plan, plan, graph

    if not settings.kernel_cognitive_planner_v2_enabled:
        raise RuntimeError("CognitivePlannerV2 is required for goal-driven planning")

    planner = ExecutionPlanner()
    cognitive_plan, plan, graph = await planner.plan_and_project(
        canonical_query, ctx, understanding=understanding
    )

    if root and plan and getattr(plan, "subtasks", None):
        for i, t in enumerate(plan.subtasks):
            if not getattr(t, "goal_id", ""):
                if i < len(subs) and isinstance(subs[i], dict):
                    t.goal_id = str(subs[i].get("goal_id", root))
                else:
                    t.goal_id = root

    try:
        from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state

        graph_obj = _goal_graph_from_dict(gg_raw)
        if graph_obj and root:
            for g in graph_obj.goals:
                if g.goal_id == root:
                    transition_goal_state(g, GoalLifecycleState.PROJECTED)
                    break
    except Exception:
        pass

    return cognitive_plan, plan, graph


def _goal_graph_from_dict(raw: dict[str, Any]) -> Any | None:
    if not raw.get("goals"):
        return None
    from kernel.protocol.runtime_contract import Goal, GoalGraph

    goals = []
    for g in raw["goals"]:
        if not isinstance(g, dict):
            continue
        goals.append(
            Goal(
                goal_id=str(g.get("goal_id", "")),
                description=str(g.get("description", "")),
                priority=int(g.get("priority", 0)),
                parent_id=g.get("parent_id"),
                metadata=dict(g.get("metadata") or {}),
            )
        )
    return GoalGraph(
        root_goal_id=str(raw.get("root_goal_id", "")),
        goals=goals,
        intent_category=str(raw.get("intent_category", "general")),
        protected_intent=str(raw.get("protected_intent", "")),
    )


_DOMAIN_CAP = {
    "data_query": "data.query",
    "web_search": "web.search",
    "document_retrieval": "rag.retrieve",
    "tool_execution": "tool.datetime",
    "general_qa": "model.answer",
}


async def try_build_goal_only_execution_graph(
    canonical_query: str,
    ctx: Any,
    gg_raw: dict[str, Any],
    subs: list[dict[str, Any]],
    root: str,
    understanding: Any = None,
) -> tuple[Any, Any, Any] | None:
    """One execution node per sub-goal when kernel_goal_driven_dag_enabled."""
    from kernel.runtime.objects import ExecutionPlan, ExecutionTask

    intent = str(gg_raw.get("intent_category", "general") or "general")
    subtasks: list[ExecutionTask] = []
    for i, g in enumerate(subs):
        if not isinstance(g, dict):
            continue
        domain = str((g.get("metadata") or {}).get("domain") or intent)
        cap = _DOMAIN_CAP.get(domain, "model.answer")
        subtasks.append(
            ExecutionTask(
                task_id=f"goal_{g.get('goal_id', i)}",
                goal_id=str(g.get("goal_id", root)),
                capability_type=cap,
                query=str(g.get("description") or canonical_query)[:500],
                params={"goal_driven": True},
            )
        )
    if not subtasks:
        return None
    plan = ExecutionPlan(
        plan_id=str(getattr(ctx, "request_id", "")),
        rewritten_query=canonical_query,
        intent_category=intent,
        subtasks=subtasks,
        risk_level="medium" if len(subtasks) > 1 else "low",
    )
    graph: list[Any] = []
    try:
        from infra.config.settings import settings

        if settings.kernel_runtime_capability_graph_enabled:
            from kernel.runtime.capability_graph_builder import CapabilityGraphBuilder

            graph = await CapabilityGraphBuilder().build(plan)
    except Exception:
        graph = []

    class _StubCognitivePlan:
        def summary(self) -> str:
            return f"goal_driven_dag:{len(subtasks)}"

        cognitive_graph = type("_G", (), {"information_gaps": []})()

    return _StubCognitivePlan(), plan, graph