"""从 GoalGraph 投影世界状态，供运行时执行使用。"""

from __future__ import annotations

from typing import Any

from kernel.protocol.runtime_contract import GoalGraph


def project_goal_graph_to_world_state(graph: GoalGraph | None) -> dict[str, Any]:
    if not graph:
        return {}
    subs = [g for g in graph.goals if g.parent_id == graph.root_goal_id]
    return {
        "root_goal_id": graph.root_goal_id,
        "intent_category": graph.intent_category,
        "protected_intent": graph.protected_intent,
        "sub_goal_count": len(subs),
        "sub_goals": [
            {
                "goal_id": g.goal_id,
                "description": g.description[:200],
                "priority": g.priority,
                "domain": (g.metadata or {}).get("domain", ""),
                "lifecycle_state": (g.metadata or {}).get("lifecycle_state", "created"),
            }
            for g in sorted(subs, key=lambda x: x.priority)
        ],
    }


def project_goal_graph_to_execution_hints(goal_graph_dict: dict[str, Any]) -> dict[str, Any]:
    """Bind GoalGraph to capability / DAG hints for runtime dispatch (not planner-only)."""
    if not goal_graph_dict:
        return {}
    root = str(goal_graph_dict.get("root_goal_id", ""))
    goals = goal_graph_dict.get("goals") or []
    subs = [
        g
        for g in goals
        if isinstance(g, dict) and g.get("parent_id") == root
    ]
    domains = [
        str((g.get("metadata") or {}).get("domain") or "")
        for g in subs
        if isinstance(g, dict)
    ]
    return {
        "root_goal_id": root,
        "intent_category": goal_graph_dict.get("intent_category", "general"),
        "sub_goal_count": len(subs),
        "sub_goal_ids": [g.get("goal_id") for g in subs if isinstance(g, dict)],
        "domains": [d for d in domains if d],
        "parallel_eligible": len(subs) >= 2,
    }