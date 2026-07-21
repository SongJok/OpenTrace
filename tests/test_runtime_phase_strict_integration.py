"""Integration: strict runtime phase transitions block execute."""

from __future__ import annotations

import pytest

from infra.config.settings import settings
from kernel.protocol.behavior_contracts import enforce_phase_transition


class TestPhaseTransitionEnforce:
    def test_enforce_invalid(self):
        v = enforce_phase_transition("done", "plan", strict=True)
        assert v

    def test_executive_blocks_execute_on_violations(self):
        from kernel.runtime.cognitive_executive import CognitiveExecutive

        ex = CognitiveExecutive()
        ctx = type(
            "C",
            (),
            {"metadata": {"phase_transition_violations": ["invalid:done->plan"]}},
        )()
        old = settings.kernel_runtime_phase_transition_strict
        try:
            settings.kernel_runtime_phase_transition_strict = True
            assert ex._phase_transition_blocked(ctx) is True
        finally:
            settings.kernel_runtime_phase_transition_strict = old


class TestExecutionProjectionGoalId:
    def test_task_carries_goal_from_assignment(self):
        from kernel.runtime.cognitive.execution_projection import (
            ProjectedCapability,
            ExecutionProjection,
        )
        from kernel.runtime.objects import ExecutionTask

        proj = ExecutionProjection(
            all_nodes=[
                ProjectedCapability(
                    node_id="n1",
                    capability_type="data.query",
                    goal_id="g-root",
                    query="q",
                )
            ]
        )
        plan = proj.to_execution_plan()
        assert plan.subtasks[0].goal_id == "g-root"


class TestMultiGoalGoalIdOnNodes:
    def test_schedule_attaches_goal_id(self):
        from kernel.protocol.runtime_contract import Goal, GoalGraph
        from kernel.goal.multi_goal_scheduler import schedule_sub_goals_from_graph

        root = "r1"
        graph = GoalGraph(
            root_goal_id=root,
            goals=[
                Goal(goal_id=root, description="root", parent_id=None),
                Goal(goal_id="r1:sub:1", description="Q1", parent_id=root, priority=0),
                Goal(goal_id="r1:sub:2", description="Q2", parent_id=root, priority=1),
            ],
        )
        sq = [{"text": "Q1"}, {"text": "Q2"}]
        out = schedule_sub_goals_from_graph(graph, sq)
        assert out[0].get("goal_id") == "r1:sub:1"
        assert out[1].get("goal_id") == "r1:sub:2"