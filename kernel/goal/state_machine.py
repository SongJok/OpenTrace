"""目标状态机 — 运行时世界的目标演化（不仅是规划器输入）。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from kernel.protocol.runtime_contract import Goal, GoalGraph


class GoalLifecycleState(str, Enum):
    CREATED = "created"
    PROJECTED = "projected"
    ACTIVE = "active"
    EXECUTING = "executing"
    WAITING = "waiting"
    BLOCKED = "blocked"
    REPLANNING = "replanning"
    EVIDENCE_COLLECTED = "evidence_collected"
    FUSED = "fused"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


_VALID_TRANSITIONS: dict[GoalLifecycleState, set[GoalLifecycleState]] = {
    GoalLifecycleState.CREATED: {
        GoalLifecycleState.PROJECTED,
        GoalLifecycleState.FAILED,
        GoalLifecycleState.BLOCKED,
    },
    GoalLifecycleState.PROJECTED: {
        GoalLifecycleState.ACTIVE,
        GoalLifecycleState.EXECUTING,
        GoalLifecycleState.WAITING,
        GoalLifecycleState.BLOCKED,
        GoalLifecycleState.FAILED,
    },
    GoalLifecycleState.ACTIVE: {
        GoalLifecycleState.EXECUTING,
        GoalLifecycleState.WAITING,
        GoalLifecycleState.BLOCKED,
        GoalLifecycleState.REPLANNING,
        GoalLifecycleState.FAILED,
    },
    GoalLifecycleState.EXECUTING: {
        GoalLifecycleState.EVIDENCE_COLLECTED,
        GoalLifecycleState.WAITING,
        GoalLifecycleState.REPLANNING,
        GoalLifecycleState.BLOCKED,
        GoalLifecycleState.FAILED,
    },
    GoalLifecycleState.WAITING: {
        GoalLifecycleState.EXECUTING,
        GoalLifecycleState.ACTIVE,
        GoalLifecycleState.BLOCKED,
        GoalLifecycleState.FAILED,
    },
    GoalLifecycleState.BLOCKED: {
        GoalLifecycleState.PROJECTED,
        GoalLifecycleState.FAILED,
        GoalLifecycleState.ARCHIVED,
    },
    GoalLifecycleState.REPLANNING: {
        GoalLifecycleState.PROJECTED,
        GoalLifecycleState.EXECUTING,
        GoalLifecycleState.FAILED,
    },
    GoalLifecycleState.EVIDENCE_COLLECTED: {
        GoalLifecycleState.FUSED,
        GoalLifecycleState.FAILED,
    },
    GoalLifecycleState.FUSED: {
        GoalLifecycleState.COMPLETED,
        GoalLifecycleState.FAILED,
    },
    GoalLifecycleState.COMPLETED: {GoalLifecycleState.ARCHIVED},
    GoalLifecycleState.FAILED: {
        GoalLifecycleState.ARCHIVED,
        GoalLifecycleState.PROJECTED,
    },
    GoalLifecycleState.ARCHIVED: set(),
}


def transition_goal_state(
    goal: Goal,
    new_state: GoalLifecycleState,
) -> GoalLifecycleState:
    current_raw = (goal.metadata or {}).get("lifecycle_state", GoalLifecycleState.CREATED.value)
    try:
        current = GoalLifecycleState(current_raw)
    except ValueError:
        current = GoalLifecycleState.CREATED
    allowed = _VALID_TRANSITIONS.get(current, set())
    if new_state not in allowed and new_state != current:
        goal.metadata = dict(goal.metadata or {})
        goal.metadata["lifecycle_state"] = current.value
        goal.metadata["lifecycle_transition_rejected"] = new_state.value
        return current
    if new_state != current:
        from kernel.goal.goal_transition import record_goal_transition

        record_goal_transition(
            goal,
            from_state=current,
            to_state=new_state,
            reason="state_machine",
        )
    goal.metadata = dict(goal.metadata or {})
    goal.metadata["lifecycle_state"] = new_state.value
    goal.metadata.pop("lifecycle_transition_rejected", None)
    return new_state


def initialize_graph_states(graph: GoalGraph) -> None:
    for g in graph.goals:
        if "lifecycle_state" not in (g.metadata or {}):
            g.metadata = dict(g.metadata or {})
            g.metadata["lifecycle_state"] = GoalLifecycleState.CREATED.value