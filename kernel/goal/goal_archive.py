"""Goal archive — terminal lifecycle compaction for replay and retention."""

from __future__ import annotations

from typing import Any

from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state
from kernel.protocol.runtime_contract import Goal, GoalGraph


def archive_goal(goal: Goal, *, reason: str = "turn_complete") -> GoalLifecycleState:
    st = transition_goal_state(goal, GoalLifecycleState.ARCHIVED)
    if st == GoalLifecycleState.ARCHIVED:
        hist = (goal.metadata or {}).get("lifecycle_transitions") or []
        if hist:
            hist[-1]["reason"] = reason
            hist[-1]["ref_type"] = "archive"
            goal.metadata["lifecycle_transitions"] = hist
    return st


def archive_completed_graph(graph: GoalGraph | None, *, reason: str = "graph_complete") -> int:
    if not graph:
        return 0
    n = 0
    for g in graph.goals:
        state = (g.metadata or {}).get("lifecycle_state", "")
        if state in (
            GoalLifecycleState.COMPLETED.value,
            GoalLifecycleState.FAILED.value,
        ):
            archive_goal(g, reason=reason)
            n += 1
    return n


def archive_snapshot(graph: GoalGraph | None) -> dict[str, Any]:
    if not graph:
        return {"root_goal_id": "", "goals": []}
    return {
        "root_goal_id": graph.root_goal_id,
        "goals": [
            {
                "goal_id": g.goal_id,
                "lifecycle_state": (g.metadata or {}).get("lifecycle_state"),
                "transitions": (g.metadata or {}).get("lifecycle_transitions", [])[-8:],
            }
            for g in graph.goals
        ],
    }