"""Regression for deepened vNext gaps (state bus, multi-goal resources, slim gateway stream)."""

from __future__ import annotations

import inspect


class TestCognitiveStateBus:
    def test_bind_state_to_context(self):
        from kernel.runtime.cognitive_state.bus import bind_state_to_context

        ctx = type("C", (), {"request_id": "r1", "session_id": "s1", "metadata": {}})()
        rs = bind_state_to_context(ctx)
        assert ctx.metadata["cognitive_runtime_state"]["goal_id"] == rs.goal_id or rs.goal_id == ""


class TestMultiGoalResources:
    def test_resource_plan_slots(self):
        from kernel.goal.multi_goal_resources import project_multi_goal_resource_plan
        from kernel.protocol.runtime_contract import Goal, GoalGraph

        g = GoalGraph(
            root_goal_id="root",
            goals=[
                Goal(goal_id="root", description="root"),
                Goal(goal_id="s1", parent_id="root", priority=0, description="a"),
                Goal(goal_id="s2", parent_id="root", priority=1, description="b"),
            ],
        )
        plan = project_multi_goal_resource_plan(g, cognitive_budget={"max_capabilities": 2})
        assert plan["sub_goal_count"] == 2
        assert len(plan["resource_slots"]) == 2


class TestRuntimeGatewayStreamSlim:
    def test_stream_no_goal_graph_in_gateway(self):
        from kernel import runtime_gateway as rg

        src = inspect.getsource(rg.RuntimeGateway.stream)
        assert 'request.metadata["goal_graph"]' not in src


class TestEvolutionRouterFabricBind:
    def test_store_calls_bind_when_enabled(self):
        from memory.evolution import router as er

        src = inspect.getsource(er.EvolutionMemoryRouter.store)
        assert "bind_turn_memory" in src


class TestAdaptiveRiskDispatch:
    def test_dispatch_enrichment_sets_adaptive_risk(self):
        from kernel.cognitive_supervisor.dispatch_enrichment import apply_dispatch_enrichment

        src = inspect.getsource(apply_dispatch_enrichment)
        assert "AdaptiveRiskEngine" in src
        assert "adaptive_risk" in src

    def test_governance_center_merges_adaptive_risk(self):
        from kernel.governance.governance_center import get_governance_center

        b = get_governance_center().evaluate_turn(
            evidence_count=0,
            fusion_confidence=0.0,
            hallucination_risk=0.7,
            critic_passed=False,
            route="test",
            sub_goal_count=5,
            adaptive_risk_level="high",
            adaptive_risk_score=0.65,
        )
        assert b.semantic_observability.get("adaptive_risk", {}).get("level") in (
            "high",
            "medium",
            "low",
        )


class TestV4ImportBoundaryKernel:
    def test_runtime_gateway_no_orchestrator_v4(self):
        gw = __import__("pathlib").Path(__file__).resolve().parents[1] / "kernel" / "runtime_gateway.py"
        text = gw.read_text(encoding="utf-8")
        assert "orchestrator_v4" not in text