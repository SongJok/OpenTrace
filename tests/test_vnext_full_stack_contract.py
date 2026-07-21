"""vNext 全栈集成契约（门面、治理中心、P2 规划器）。"""

from __future__ import annotations

class TestStrategyDomain:
    def test_capability_chain_rag(self):
        from kernel.strategy.capability_chain import resolve_capability_chain

        link = resolve_capability_chain("rag.retrieve", force_mode="rag")
        assert link.capability.capability_type == "rag.retrieve"
        assert "rag" in link.tool_names

class TestWorldModelFacade:
    def test_cognitive_world_model_singleton(self):
        from kernel.cognition.cognitive_world_model import get_cognitive_world_model

        wm = get_cognitive_world_model()
        g = wm.ground("华东")
        assert g.canonical_name

class TestGovernanceCenter:
    def test_evaluate_turn_bundle(self):
        from kernel.governance import get_governance_center

        b = get_governance_center().evaluate_turn(
            evidence_count=2,
            fusion_confidence=0.8,
            hallucination_risk=0.1,
            critic_passed=True,
            route="test",
        )
        assert "semantic_observability" in b.__dict__ or b.semantic_observability
        assert b.evidence.get("passed") is True

class TestP2MultiPlannerModule:
    def test_build_multi_graph_empty_subs(self):
        import asyncio
        from kernel.cognitive_kernel import KernelRequest
        from kernel.cognition.multi_execution_planner import build_multi_execution_graph

        req = KernelRequest(query="a？b？", metadata={"intent_lock": {}})
        nodes, _ = asyncio.run(build_multi_execution_graph(req, []))
        assert nodes == []