"""Enterprise gaps closure — goal lifecycle, governance single path, flags, world model."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from infra.config.flag_registry import duplicate_settings_field_names, validate_flag_dependencies
from infra.config.settings import Settings
from kernel.goal.goal_recovery import mark_goals_blocked_for_governance, recover_goal_to_projected
from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state
from kernel.protocol.behavior_contracts import RuntimePhase, assert_phase_transition
from kernel.protocol.runtime_contract import Goal, GoalGraph


ROOT = Path(__file__).resolve().parents[1]

_POLICY_REEXPORTS = [
    "governance/adaptive_risk_engine.py",
    "governance/semantic_metrics.py",
    "governance/cognitive_policy_engine.py",
    "governance/runtime_policy_engine.py",
    "governance/semantic_metrics_pipeline.py",
]


class TestGoalLifecycleEnterprise:
    def test_blocked_and_waiting_states_exist(self):
        assert GoalLifecycleState.BLOCKED.value == "blocked"
        assert GoalLifecycleState.WAITING.value == "waiting"

    def test_governance_denial_marks_blocked(self):
        g = Goal(goal_id="g1", description="x")
        graph = GoalGraph(root_goal_id="g1", goals=[g])
        transition_goal_state(g, GoalLifecycleState.PROJECTED)
        mark_goals_blocked_for_governance(graph, violations=["missing_goal"])
        assert g.metadata["lifecycle_state"] == "blocked"
        assert g.metadata.get("lifecycle_transitions")

    def test_failed_recovery_to_projected(self):
        g = Goal(goal_id="g2", description="y")
        transition_goal_state(g, GoalLifecycleState.PROJECTED)
        transition_goal_state(g, GoalLifecycleState.FAILED)
        st = recover_goal_to_projected(g)
        assert st == GoalLifecycleState.PROJECTED

    def test_runtime_phase_waiting_replanning(self):
        assert assert_phase_transition(RuntimePhase.PLAN.value, RuntimePhase.WAITING.value)
        assert assert_phase_transition(RuntimePhase.EXECUTE.value, RuntimePhase.REPLANNING.value)


class TestGovernanceCanonicalEngines:
    def test_governance_center_imports_kernel_engines_only(self):
        path = ROOT / "kernel/governance/governance_center.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("governance.") and not node.module.startswith(
                    "kernel.governance."
                ):
                    pytest.fail(f"governance_center must not import {node.module}")

    @pytest.mark.parametrize("rel", _POLICY_REEXPORTS)
    def test_top_level_policy_modules_reexport_only(self, rel: str):
        path = ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        class_defs = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        assert class_defs == [], f"{rel} must not define classes"
        imports_kernel = any(
            isinstance(n, ast.ImportFrom) and (n.module or "").startswith("kernel.governance")
            for n in tree.body
        )
        assert imports_kernel, f"{rel} must re-export from kernel.governance"


class TestFlagRegistry:
    def test_no_duplicate_settings_fields(self):
        assert duplicate_settings_field_names(Settings) == []

    def test_strict_phase_requires_v5_when_both_on(self):
        s = Settings(
            app_env="development",
            kernel_v5_routing_enabled=False,
            kernel_runtime_phase_transition_strict=True,
            gateway_port=14100,
            app_port=14100,
        )
        violations = validate_flag_dependencies(s)
        assert "kernel_runtime_phase_transition_strict_requires_kernel_v5_routing_enabled" in violations


class TestWorldModelGoalSlice:
    def test_grounding_includes_goal_slice_and_version(self):
        from kernel.cognition.runtime_grounding import RuntimeGroundingState, bump_world_state_version

        state = RuntimeGroundingState()
        bump_world_state_version(state, request_id="r1")
        d = state.to_dict()
        assert d["world_state_id"]
        assert d["goal"]["version"] >= 1