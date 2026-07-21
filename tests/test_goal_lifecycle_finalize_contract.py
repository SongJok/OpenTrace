"""Goal turn-close lifecycle — enterprise audit trail."""

from __future__ import annotations

from kernel.goal.goal_lifecycle import finalize_turn_goal_lifecycle
from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state
from kernel.protocol.runtime_contract import Goal, GoalGraph


class TestFinalizeTurnGoalLifecycle:
    def test_root_closes_to_archived_after_success(self):
        root = Goal(goal_id="r1", description="q")
        transition_goal_state(root, GoalLifecycleState.PROJECTED)
        transition_goal_state(root, GoalLifecycleState.ACTIVE)
        graph = GoalGraph(root_goal_id="r1", goals=[root], intent_category="general")
        out = finalize_turn_goal_lifecycle(graph, critic_passed=True)
        assert out["archived_count"] == 1
        assert root.metadata["lifecycle_state"] == GoalLifecycleState.ARCHIVED.value
        assert "lifecycle_transitions" in root.metadata

    def test_critic_fail_marks_failed_then_archived(self):
        root = Goal(goal_id="r2", description="q")
        transition_goal_state(root, GoalLifecycleState.ACTIVE)
        graph = GoalGraph(root_goal_id="r2", goals=[root])
        finalize_turn_goal_lifecycle(graph, critic_passed=False)
        assert root.metadata["lifecycle_state"] == GoalLifecycleState.ARCHIVED.value
        hist = root.metadata.get("lifecycle_transitions") or []
        states = [h["to_state"] for h in hist]
        assert GoalLifecycleState.FAILED.value in states

    def test_skips_created_subgoals(self):
        root = Goal(goal_id="r3", description="root")
        sub = Goal(goal_id="s1", description="sub", parent_id="r3")
        transition_goal_state(root, GoalLifecycleState.ACTIVE)
        graph = GoalGraph(root_goal_id="r3", goals=[root, sub])
        finalize_turn_goal_lifecycle(graph, critic_passed=True)
        sub_state = (sub.metadata or {}).get("lifecycle_state")
        assert sub_state in (None, GoalLifecycleState.CREATED.value)
        assert root.metadata["lifecycle_state"] == GoalLifecycleState.ARCHIVED.value