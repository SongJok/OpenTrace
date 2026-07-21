"""目标图执行后演化 — 将证据/记忆绑定到目标。"""

from __future__ import annotations

from typing import Any

from kernel.goal.goal_memory_binding import bind_goal_turn_to_memory_fabric
from kernel.protocol.runtime_contract import GoalGraph


def evolve_goals_after_execution(
    goal_graph: GoalGraph | None,
    *,
    request_id: str,
    session_id: str,
    evidence_ids: list[str] | None = None,
    artifact_id: str = "",
) -> dict[str, Any]:
    """轮次后目标演化钩子（记忆织物 + 元数据）。"""
    if not goal_graph:
        return {}
    root = goal_graph.root_goal_id
    bind_goal_turn_to_memory_fabric(
        session_id=session_id,
        request_id=request_id,
        goal_id=root,
        route="cognitive_runtime_v2",
    )
    return {
        "root_goal_id": root,
        "goal_count": len(goal_graph.goals),
        "artifact_id": artifact_id,
        "evidence_bound": len(evidence_ids or []),
    }