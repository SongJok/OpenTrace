"""Goal recovery — retry / unblock after failure or governance denial."""

from __future__ import annotations

from typing import Any

from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state
from kernel.protocol.runtime_contract import Goal, GoalGraph


def can_recover_goal(goal: Goal) -> bool:
    md = goal.metadata or {}
    state = md.get("lifecycle_state", GoalLifecycleState.CREATED.value)
    if state in (GoalLifecycleState.COMPLETED.value, GoalLifecycleState.ARCHIVED.value):
        return False
    if state == GoalLifecycleState.FAILED.value:
        return True
    if state == GoalLifecycleState.BLOCKED.value:
        return bool(md.get("recoverable", True))
    return False


def recover_goal_to_projected(goal: Goal, *, reason: str = "manual_recovery") -> GoalLifecycleState:
    """Reset a failed/blocked goal to PROJECTED when policy allows."""
    if not can_recover_goal(goal):
        raw = (goal.metadata or {}).get("lifecycle_state", GoalLifecycleState.CREATED.value)
        try:
            return GoalLifecycleState(raw)
        except ValueError:
            return GoalLifecycleState.CREATED
    st = transition_goal_state(goal, GoalLifecycleState.PROJECTED)
    if st == GoalLifecycleState.PROJECTED:
        hist = (goal.metadata or {}).get("lifecycle_transitions") or []
        if hist:
            hist[-1]["reason"] = reason
            hist[-1]["ref_type"] = "recovery"
            goal.metadata["lifecycle_transitions"] = hist
    return st


def mark_goals_blocked_for_governance(graph: GoalGraph | None, *, violations: list[str]) -> None:
    if not graph:
        return
    ref = ",".join(violations[:8])
    for g in graph.goals:
        transition_goal_state(g, GoalLifecycleState.BLOCKED)
        hist = (g.metadata or {}).get("lifecycle_transitions") or []
        if hist:
            hist[-1]["reason"] = "governance_denied"
            hist[-1]["ref_type"] = "violation"
            hist[-1]["ref_id"] = ref
            g.metadata["lifecycle_transitions"] = hist