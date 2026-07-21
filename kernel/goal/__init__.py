"""Goal runtime — first-class lifecycle, projection, evidence, memory, evolution."""

from kernel.goal.goal_evidence_binding import (
    build_goal_evidence_binding,
    extract_evidence_ids,
    merge_binding_into_artifact_trace,
    stamp_evidence_goal_ids,
)
from kernel.goal.goal_evolution import evolve_goals_after_execution
from kernel.goal.goal_execution_outcomes import record_goal_execution_outcomes
from kernel.goal.multi_goal_outcomes import (
    build_sub_goal_bindings,
    evolve_sub_goals_after_multi_execution,
)
from kernel.goal.goal_archive import archive_completed_graph, archive_goal, archive_snapshot
from kernel.goal.goal_lifecycle import bind_goal_graph_to_context, finalize_turn_goal_lifecycle
from kernel.goal.goal_recovery import can_recover_goal, mark_goals_blocked_for_governance, recover_goal_to_projected
from kernel.goal.goal_transition import GoalTransition, graph_has_transition_rejection, record_goal_transition
from kernel.goal.goal_memory_binding import bind_from_runtime_context, bind_goal_turn_to_memory_fabric
from kernel.goal.goal_replay import snapshot_goal_for_replay
from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state

__all__ = [
    "GoalLifecycleState",
    "GoalTransition",
    "archive_completed_graph",
    "archive_goal",
    "archive_snapshot",
    "bind_from_runtime_context",
    "bind_goal_graph_to_context",
    "finalize_turn_goal_lifecycle",
    "bind_goal_turn_to_memory_fabric",
    "build_goal_evidence_binding",
    "build_sub_goal_bindings",
    "evolve_goals_after_execution",
    "evolve_sub_goals_after_multi_execution",
    "extract_evidence_ids",
    "merge_binding_into_artifact_trace",
    "record_goal_execution_outcomes",
    "snapshot_goal_for_replay",
    "stamp_evidence_goal_ids",
    "transition_goal_state",
    "can_recover_goal",
    "mark_goals_blocked_for_governance",
    "recover_goal_to_projected",
    "graph_has_transition_rejection",
    "record_goal_transition",
]