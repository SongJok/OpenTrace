"""
三层规划门面（vNext）：

  GoalPlanner        — 意图 / 目标图（认知层，不涉及工具）
  ExecutionPlanner   — 策略 + 执行投影（运行时认知）
  RefinementPlanner  — 事后计划精炼（refine_planner）

遗留模块仍保留；新代码应调用本门面。
"""

from __future__ import annotations

from typing import Any

from kernel.protocol.runtime_contract import Goal, GoalGraph


class GoalPlanner:
    """从 intent lock / 请求构建 GoalGraph — 仅认知层。"""

    def build_from_intent_lock(
        self, query: str, intent_lock: dict[str, Any], request_id: str
    ) -> GoalGraph:
        protected = str(intent_lock.get("protected_intent") or query)
        task_type = str(intent_lock.get("task_type") or "general_qa")
        goal = Goal(
            goal_id=request_id,
            description=protected,
            metadata={"task_type": task_type, "role": "root"},
        )
        return GoalGraph(
            root_goal_id=request_id,
            goals=[goal],
            intent_category=task_type,
            protected_intent=protected,
        )

    def build_from_request(self, request: Any) -> GoalGraph:
        """Align RuntimeTask goal graph with kernel intent_lock + optional decomposition."""
        lock = request.metadata.get("intent_lock") or {}
        goal_id = str(request.metadata.get("request_id") or request.session_id or "goal")
        if not goal_id or goal_id == "goal":
            import uuid

            goal_id = str(uuid.uuid4())
        graph = self.build_from_intent_lock(request.query, lock, goal_id)
        subs = request.metadata.get("decomposed_goals") or request.metadata.get("sub_questions")
        if subs:
            graph = self.extend_with_subgoals(graph, subs, root_id=graph.root_goal_id)
        return graph

    def extend_with_subgoals(
        self,
        graph: GoalGraph,
        sub_items: list[Any],
        root_id: str,
    ) -> GoalGraph:
        """Add child goals for multi-question / decomposed queries."""
        for i, item in enumerate(sub_items):
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("description") or "")
                domain = str(item.get("domain") or item.get("task_type") or "")
            else:
                text = str(item)
                domain = ""
            if not text.strip():
                continue
            gid = f"{root_id}:sub:{i+1}"
            graph.add_goal(
                Goal(
                    goal_id=gid,
                    description=text.strip(),
                    parent_id=root_id,
                    priority=i,
                    metadata={"domain": domain, "role": "sub_goal"},
                )
            )
        return graph


class ExecutionPlanner:
    """CognitivePlannerV2 + StrategyBuilder; projection via ProjectionPlanner."""

    async def plan_and_project(
        self,
        canonical_query: str,
        ctx: Any,
        understanding: Any = None,
    ) -> tuple[Any, Any, Any]:
        from infra.config.settings import settings
        from kernel.cognition.cognitive_planner_core import build_cognitive_plan_and_strategy
        from kernel.runtime.cognitive.projection_planner import get_projection_planner

        if not settings.kernel_cognitive_planner_v2_enabled:
            raise RuntimeError("CognitivePlannerV2 is required for ExecutionPlanner")

        cognitive_plan, strategy = await build_cognitive_plan_and_strategy(
            canonical_query, ctx, understanding=understanding
        )
        plan, graph = get_projection_planner().project(
            strategy,
            query=canonical_query,
            intent_category=getattr(understanding, "domain", "general") if understanding else "general",
            risk_level=cognitive_plan.cognitive_graph.risk_analysis.risk_level,
            completion_criteria=getattr(understanding, "completion_criteria", "") if understanding else "",
        )
        gg = (getattr(ctx, "metadata", None) or {}).get("goal_graph") or {}
        root = str(gg.get("root_goal_id", "") or getattr(ctx, "request_id", ""))
        if root and plan.subtasks:
            for t in plan.subtasks:
                if not getattr(t, "goal_id", ""):
                    t.goal_id = root
        return cognitive_plan, plan, graph


class StrategicPlanner:
    """Budget / capability / runtime-selection hints — does not build execution DAG."""

    def project_hints(self, task: Any, request: Any) -> dict[str, Any]:
        lock = request.metadata.get("intent_lock") or {}
        budget = lock.get("cognitive_budget") or {}
        graph = task.goal_graph
        sub_count = len(graph.goals) - 1 if graph and len(graph.goals) > 1 else 0
        intent = graph.intent_category if graph else "general"
        from infra.config.settings import settings

        preferred_runtime = "cognitive_executive"
        allowed = list(lock.get("allowed_capabilities") or task.constraints.allowed_capabilities or [])
        disallowed = set(lock.get("disallowed_capabilities") or task.constraints.disallowed_capabilities or [])
        data_allowed = (
            "data.query" in allowed or "data_query" in allowed
        ) and "data.query" not in disallowed and "data_query" not in disallowed
        if (
            bool(getattr(settings, "kernel_data_intelligence_routing_enabled", True))
            and (intent == "data_query" or lock.get("task_type") == "data_query")
            and data_allowed
        ):
            preferred_runtime = "data_intelligence"
        elif sub_count >= 2:
            preferred_runtime = "multi_goal"
        return {
            "preferred_runtime": preferred_runtime,
            "sub_goal_count": sub_count,
            "max_parallel": task.constraints.max_parallel,
            "max_replans": task.budget.max_replans,
            "intent_category": intent,
            "budget_projection": dict(budget),
        }

    def project_hints_from_context(
        self, ctx: Any, goal_execution_hints: dict[str, Any]
    ) -> dict[str, Any]:
        """Strategic layer from runtime context + goal projection (no RuntimeTask required)."""
        md = getattr(ctx, "metadata", None) or {}
        lock = md.get("intent_lock") or {}
        budget = lock.get("cognitive_budget") or getattr(ctx, "cognitive_budget", None) or {}
        intent = str(
            goal_execution_hints.get("intent_category")
            or getattr(ctx, "task_type", None)
            or "general"
        )
        sub_count = int(goal_execution_hints.get("sub_goal_count", 0) or 0)
        from infra.config.settings import settings

        preferred_runtime = "cognitive_executive"
        allowed = list(lock.get("allowed_capabilities") or [])
        disallowed = set(lock.get("disallowed_capabilities") or [])
        data_allowed = (
            "data.query" in allowed or "data_query" in allowed
        ) and "data.query" not in disallowed and "data_query" not in disallowed
        if (
            bool(getattr(settings, "kernel_data_intelligence_routing_enabled", True))
            and intent == "data_query"
            and data_allowed
        ):
            preferred_runtime = "data_intelligence"
        elif sub_count >= 2 or goal_execution_hints.get("parallel_eligible"):
            preferred_runtime = "multi_goal"
        return {
            "preferred_runtime": preferred_runtime,
            "sub_goal_count": sub_count,
            "intent_category": intent,
            "budget_projection": dict(budget) if isinstance(budget, dict) else {},
            "domains": list(goal_execution_hints.get("domains") or []),
        }


class RefinementPlanner:
    """Thin wrapper over kernel.refine_planner for post-execution refinement."""

    def __init__(self) -> None:
        from kernel.refine_planner import RefinePlanner

        self._inner = RefinePlanner()

    @property
    def inner(self) -> Any:
        return self._inner

    async def maybe_replan_after_failures(
        self,
        query: str,
        plan: Any,
        agent_results: list[Any],
        depth: int = 0,
    ) -> tuple[Any, list[Any], bool, Any | None]:
        """If any agent failed, run bounded local replan. Returns (plan, results, replanned, refined)."""
        from kernel.refine_planner import RepairStrategy

        failed = [r for r in agent_results if getattr(r, "status", "") == "error"]
        if not failed:
            return plan, agent_results, False, None
        intent = await self._inner.detect_correction(query, plan, failed[0])
        if not intent.is_correction:
            return plan, agent_results, False, None
        refined = self._inner.refine_plan(intent, plan, agent_results, query, depth=depth)
        replanned = refined.repair_strategy != RepairStrategy.ABORT
        return refined.plan or plan, agent_results, replanned, refined


def get_goal_planner() -> GoalPlanner:
    return GoalPlanner()


def get_strategic_planner() -> StrategicPlanner:
    return StrategicPlanner()