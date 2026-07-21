"""
多目标调度 — 优先级 + 依赖链（非仅扁平并行）。

GoalGraph 子目标按 priority 排序（数值小者优先），并通过 depends_on
串成链，使 ExecutionRuntime 尊重目标顺序。
"""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from kernel.protocol.runtime_contract import Goal, GoalGraph

logger = get_logger(__name__)


def schedule_sub_goals_from_graph(
    goal_graph: GoalGraph,
    sub_questions: list[dict[str, str]],
) -> list[dict[str, str]]:
    """
    按 Goal.priority 对 sub_questions 重排序，并将 goal_id 附加到每项。
    """
    if not goal_graph or not sub_questions:
        return sub_questions

    root_id = goal_graph.root_goal_id
    children: list[Goal] = [
        g for g in goal_graph.goals if g.parent_id == root_id and g.goal_id != root_id
    ]
    if not children:
        return sub_questions

    # 按描述前缀/索引映射到目标
    by_priority = sorted(children, key=lambda g: (g.priority, g.goal_id))
    ordered_sq: list[dict[str, str]] = []
    used: set[int] = set()

    for g in by_priority:
        desc = (g.description or "").strip()
        for i, sq in enumerate(sub_questions):
            if i in used:
                continue
            text = (sq.get("text") or "").strip()
            if text == desc or desc in text or text in desc:
                item = dict(sq)
                item["goal_id"] = g.goal_id
                item["priority"] = g.priority
                ordered_sq.append(item)
                used.add(i)
                break
        else:
            pass

    for i, sq in enumerate(sub_questions):
        if i not in used:
            item = dict(sq)
            item.setdefault("priority", i)
            ordered_sq.append(item)

    return ordered_sq if len(ordered_sq) == len(sub_questions) else sub_questions


def apply_goal_dependencies_to_execution_graph(
    execution_graph: list[Any],
    *,
    sequential_sub_goals: bool = True,
) -> list[Any]:
    """
    在子问题节点组之间建立 depends_on 连接（display_order / sub_question_id）。
    """
    if not execution_graph or not sequential_sub_goals:
        return execution_graph

    # 按 sub_question_id 分组节点 ID
    groups: dict[str, list[Any]] = {}
    order_keys: list[str] = []
    for node in execution_graph:
        params = getattr(node, "params", None) or {}
        sq_id = str(params.get("sub_question_id") or getattr(node, "node_id", ""))
        if sq_id not in groups:
            groups[sq_id] = []
            order_keys.append(sq_id)
        groups[sq_id].append(node)

    # 按首个节点的 display_order 对分组排序
    def _order_key(sq_id: str) -> int:
        nodes = groups[sq_id]
        if not nodes:
            return 0
        p = getattr(nodes[0], "params", None) or {}
        return int(p.get("display_order", 0) or 0)

    order_keys.sort(key=_order_key)

    prev_last_node_id: str | None = None
    for sq_id in order_keys:
        nodes = groups[sq_id]
        if prev_last_node_id:
            for node in nodes:
                deps = list(getattr(node, "depends_on", None) or [])
                if prev_last_node_id not in deps:
                    deps.append(prev_last_node_id)
                node.depends_on = deps
        if nodes:
            prev_last_node_id = getattr(nodes[-1], "node_id", None) or prev_last_node_id

    return execution_graph


def annotate_goal_lifecycle_for_subgoals(goal_graph: GoalGraph) -> None:
    """进入多目标运行时时将子目标标记为 PROJECTED。"""
    from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state

    for g in goal_graph.goals:
        if g.parent_id and g.goal_id != goal_graph.root_goal_id:
            transition_goal_state(g, GoalLifecycleState.PROJECTED)