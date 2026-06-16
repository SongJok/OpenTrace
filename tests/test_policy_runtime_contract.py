"""Policy Runtime mutation hooks."""

from __future__ import annotations

from kernel.governance.policy_runtime import get_policy_runtime
from kernel.protocol.behavior_contracts import ReplayContract


class TestPolicyRuntime:
    def test_evidence_fusion_blocks_insufficient(self):
        d = get_policy_runtime().on_evidence_fusion(
            evidence_count=0, min_required=2, hallucination_risk=0.0
        )
        assert d.allowed is False
        assert "insufficient_evidence" in d.violations

    def test_replay_requires_root_goal(self):
        d = get_policy_runtime().on_replay_load(
            {"request_id": "r1", "session_id": "s1", "root_goal_id": ""}
        )
        assert d.allowed is False

    def test_replay_valid(self):
        d = get_policy_runtime().on_replay_load(
            {
                "request_id": "r1",
                "session_id": "s1",
                "root_goal_id": "g1",
                "artifact_id": "a1",
            }
        )
        assert d.allowed is True

    def test_governance_center_replay_mutation(self):
        from kernel.governance.governance_center import get_governance_center

        r = get_governance_center().evaluate_replay_mutation(
            {"request_id": "r1", "session_id": "s1", "root_goal_id": "g1"}
        )
        assert r["allowed"] is True

    def test_governance_center_planning_mutation(self):
        from types import SimpleNamespace

        from kernel.governance.governance_center import get_governance_center

        ctx = SimpleNamespace(
            task_type="general",
            allowed_capabilities=[],
            cognitive_budget={"max_reasoning_steps": 10},
            metadata={"goal_graph": {"goals": [{"goal_id": "g1"}], "intent_category": "general"}},
        )
        out = get_governance_center().evaluate_planning_mutation(ctx)
        assert "allowed" in out
        assert "violations" in out