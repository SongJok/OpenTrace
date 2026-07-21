"""将 GoalGraph 绑定到运行时上下文与 Artifact 元数据。"""

from __future__ import annotations

from typing import Any

from kernel.goal.goal_archive import archive_completed_graph, archive_snapshot
from kernel.goal.state_machine import GoalLifecycleState, initialize_graph_states, transition_goal_state
from kernel.protocol.runtime_contract import GoalGraph, RuntimeTask


def bind_goal_graph_to_context(ctx: Any, runtime_task: RuntimeTask) -> None:
    if not runtime_task.goal_graph:
        return
    initialize_graph_states(runtime_task.goal_graph)
    transition_goal_state(runtime_task.goal, GoalLifecycleState.PROJECTED)
    transition_goal_state(runtime_task.goal, GoalLifecycleState.ACTIVE)
    ctx.metadata = ctx.metadata or {}
    ctx.metadata["goal_graph"] = runtime_task.goal_graph.to_dict()
    ctx.metadata["root_goal_id"] = runtime_task.goal_graph.root_goal_id


def _goal_current_state(goal: Any) -> GoalLifecycleState:
    raw = (goal.metadata or {}).get("lifecycle_state", GoalLifecycleState.CREATED.value)
    try:
        return GoalLifecycleState(raw)
    except ValueError:
        return GoalLifecycleState.CREATED


def _advance_goal_chain(
    goal: Any,
    states: list[GoalLifecycleState],
    *,
    reason: str,
    ref_type: str = "",
) -> None:
    for st in states:
        before = _goal_current_state(goal)
        transition_goal_state(goal, st)
        after = _goal_current_state(goal)
        if after == st and before != st:
            hist = (goal.metadata or {}).get("lifecycle_transitions") or []
            if hist:
                hist[-1]["reason"] = reason
                if ref_type:
                    hist[-1]["ref_type"] = ref_type
                goal.metadata["lifecycle_transitions"] = hist


def finalize_turn_goal_lifecycle(
    graph: GoalGraph | None,
    *,
    critic_passed: bool | None,
    policy_denied: bool = False,
    archive_terminal: bool = True,
) -> dict[str, Any]:
    """Close the turn on GoalGraph: evidence → fuse → complete/fail → optional archive."""
    if not graph:
        return {}
    if policy_denied:
        for g in graph.goals:
            transition_goal_state(g, GoalLifecycleState.BLOCKED)
        return {
            "root_goal_id": graph.root_goal_id,
            "goal_graph": graph.to_dict(),
            "goal_archive_snapshot": archive_snapshot(graph),
            "archived_count": 0,
        }

    terminal = (
        GoalLifecycleState.COMPLETED
        if critic_passed is not False
        else GoalLifecycleState.FAILED
    )
    close_chain = [
        GoalLifecycleState.EXECUTING,
        GoalLifecycleState.EVIDENCE_COLLECTED,
        GoalLifecycleState.FUSED,
        terminal,
    ]
    for g in graph.goals:
        cur = _goal_current_state(g)
        if cur == GoalLifecycleState.ARCHIVED:
            continue
        if g.goal_id == graph.root_goal_id:
            prep: list[GoalLifecycleState] = []
            if cur == GoalLifecycleState.CREATED:
                prep = [GoalLifecycleState.PROJECTED, GoalLifecycleState.ACTIVE]
            elif cur == GoalLifecycleState.PROJECTED:
                prep = [GoalLifecycleState.ACTIVE]
            if prep:
                _advance_goal_chain(g, prep, reason="turn_prep_root", ref_type="runtime")
            _advance_goal_chain(
                g,
                close_chain,
                reason="turn_close_root",
                ref_type="runtime",
            )
        elif cur == GoalLifecycleState.CREATED:
            continue
        elif cur in (
            GoalLifecycleState.EXECUTING,
            GoalLifecycleState.EVIDENCE_COLLECTED,
            GoalLifecycleState.FUSED,
            GoalLifecycleState.ACTIVE,
            GoalLifecycleState.PROJECTED,
        ):
            _advance_goal_chain(
                g,
                [
                    GoalLifecycleState.EVIDENCE_COLLECTED,
                    GoalLifecycleState.FUSED,
                    terminal,
                ],
                reason="turn_close_subgoal",
                ref_type="runtime",
            )

    archived = archive_completed_graph(graph, reason="turn_complete") if archive_terminal else 0
    return {
        "root_goal_id": graph.root_goal_id,
        "goal_graph": graph.to_dict(),
        "goal_archive_snapshot": archive_snapshot(graph),
        "archived_count": archived,
    }