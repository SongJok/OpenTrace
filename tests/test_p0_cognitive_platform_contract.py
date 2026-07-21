"""P0: GoalSupervisor, BusinessSemantic, CognitiveIteration, StrategyPattern."""

from __future__ import annotations

from types import SimpleNamespace

from kernel.goal.goal_supervisor import enrich_goal_graph_from_request
from kernel.protocol.runtime_contract import Goal, GoalGraph


class TestGoalSupervisorContract:
    def test_business_overview_splits_into_axes(self):
        root_id = "g-root"
        graph = GoalGraph(
            root_goal_id=root_id,
            goals=[Goal(goal_id=root_id, description="本季度业务情况怎么样")],
            intent_category="data_query",
        )
        decision = enrich_goal_graph_from_request(
            graph, query="本季度业务情况怎么样", request_metadata={}
        )
        subs = [
            g
            for g in decision.graph.goals
            if g.parent_id == root_id
        ]
        assert decision.split_from_root is True
        assert len(subs) >= 2
        meta = decision.to_metadata()["goal_supervisor"]
        assert meta["goal_count"] == len(decision.graph.goals)

    def test_prepare_dispatch_invokes_goal_supervisor(self):
        import inspect

        from kernel.cognitive_supervisor import prepare_dispatch as pd

        assert "apply_goal_supervisor_to_request" in inspect.getsource(
            pd.runtime_task_from_request
        )


class TestBusinessSemanticContract:
    def test_infer_kpis_from_sales_query(self):
        from agents.data_agent_v2.business_semantic_agent import infer_business_kpis

        kpis = infer_business_kpis("最近销售同比环比怎么样")
        ids = {k["kpi_id"] for k in kpis}
        assert "revenue" in ids or "period_compare" in ids

    def test_dag_includes_business_semantic_when_enabled(self):
        from agents.data_agent_v2.dag_builder import build_cognitive_dag, validate_dag_spec

        enabled = {
            "intent": True,
            "entity": True,
            "metric": True,
            "time": True,
            "join": False,
            "semantic": True,
            "business_semantic": True,
            "planner": True,
            "compiler": True,
            "verifier": True,
        }
        spec = build_cognitive_dag("GMV", enabled=enabled)
        ids = {n.node_id for n in spec.nodes}
        assert "business_semantic" in ids
        assert not validate_dag_spec(spec)


class TestCognitiveIterationContract:
    def test_triggers_on_failed_critic(self):
        from kernel.runtime.cognitive_iteration import should_trigger_cognitive_replan

        ctx = SimpleNamespace(metadata={})
        ctx.cognitive_budget = {"max_replans": 3}
        critic = SimpleNamespace(passed=False, hallucination_risk=0.9, factuality=0.2)
        ok, reason = should_trigger_cognitive_replan(
            critic_result=critic,
            evidence_count=2,
            fusion_confidence=0.8,
            ctx=ctx,
        )
        assert ok is True
        assert reason == "critic_hallucination_risk"


class TestStrategyPatternContract:
    def test_top_k_for_planner(self):
        from kernel.capability_intelligence.strategy_pattern import (
            record_turn_pattern,
            top_k_patterns_for_planner,
        )

        record_turn_pattern(
            intent_category="data_query",
            capabilities_used=["data_query"],
            strategy_type="sequential",
            success=True,
            latency_ms=120,
            query_preview="sales",
        )
        hints = top_k_patterns_for_planner("data_query", capabilities=["data_query"], k=2)
        assert len(hints) >= 1
        assert "strategy_type" in hints[0]

    def test_supervisor_injects_strategy_patterns(self):
        import inspect

        from kernel.cognitive_supervisor import supervisor as sup

        src = inspect.getsource(sup.CognitiveSupervisor._inject_strategy_projection)
        assert "strategy_patterns" in src