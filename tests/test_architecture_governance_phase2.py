"""Architecture governance phase 2 — fabric, policies, capability contract."""

from __future__ import annotations

class TestContextFabricDynamic:
    def test_evolve_runtime_session(self):
        from kernel.context_fabric import get_context_fabric

        fab = get_context_fabric()
        d1 = fab.evolve_runtime("s-fab", goal_id="g1", runtime_phase="plan")
        d2 = fab.evolve_runtime("s-fab", evidence_ref="ev-1")
        assert "nodes" in d1
        g = fab.get_session_graph("s-fab")
        assert len(g["nodes"]) >= 2

class TestGovernanceEngines:
    def test_cognitive_policy_sub_goals(self):
        from governance.cognitive_policy_engine import CognitivePolicyEngine

        d = CognitivePolicyEngine().evaluate_planning(
            intent_category="general",
            sub_goal_count=10,
            max_steps=5,
        )
        assert d.allowed is False

    def test_evidence_policy(self):
        from governance.evidence_policy_engine import EvidencePolicyEngine

        d = EvidencePolicyEngine().evaluate_fusion(evidence_count=0, min_required=2)
        assert d.allow_fusion is False

    def test_adaptive_risk(self):
        from governance.adaptive_risk_engine import AdaptiveRiskEngine

        s = AdaptiveRiskEngine().score_turn(hallucination_risk=0.9, replanned=True)
        assert s.level in ("medium", "high")

class TestCapabilityRuntime:
    def test_contract_validate(self):
        from kernel.capability_runtime.contract import validate_capability_execution
        from kernel.protocol.runtime_contract import CapabilityRef

        v = validate_capability_execution(CapabilityRef(capability_type="data_query"))
        assert v == []

    def test_topology(self):
        from kernel.capability_runtime.topology import dependents_of

        assert "fusion" in dependents_of("data_query")

class TestBehaviorContract:
    def test_phase_transition(self):
        from kernel.protocol.behavior_contracts import assert_phase_transition

        assert assert_phase_transition("plan", "execute") is True
        assert assert_phase_transition("done", "plan") is False

class TestRuntimeGrounding:
    def test_project_from_context(self):
        from kernel.cognition.runtime_grounding import get_grounding, project_from_context

        ctx = type("C", (), {"session_id": "s", "metadata": {}, "request_id": "r"})()
        st = project_from_context(ctx)
        assert get_grounding("s") is st

class TestMemoryFabricSalience:
    def test_rank(self):
        from memory.fabric.salience_engine import rank_memory_items

        items = [{"content": "a", "score": 0.3}, {"content": "b", "score": 0.9, "goal_id": "g1"}]
        ranked = rank_memory_items(items, goal_id="g1", limit=2)
        assert ranked[0]["content"] == "b"


class TestSemanticMetricsPipeline:
    def test_session_trend_after_turns(self):
        from governance.semantic_metrics_pipeline import get_semantic_metrics_pipeline

        pipe = get_semantic_metrics_pipeline()
        pipe.record_turn(
            "s-metrics",
            evidence_count=2,
            fusion_confidence=0.9,
            hallucination_risk=0.1,
            critic_passed=True,
        )
        trend = pipe.session_trend("s-metrics")
        assert trend["turns"] >= 1
        assert "avg_reasoning_drift" in trend


class TestExecutionGuardrails:
    def test_disallowed_capability(self):
        from governance.execution_guardrails import ExecutionGuardrails

        d = ExecutionGuardrails().evaluate_dispatch(
            "web_search",
            disallowed_list=["web_search"],
        )
        assert d.allowed is False


class TestEpisodicBind:
    def test_remember_turn(self):
        from memory.fabric import remember_turn

        out = remember_turn(
            session_id="s-ep",
            request_id="r1",
            goal_id="g1",
            query="q",
            answer_preview="a",
            route="test",
            evidence_ids=["e1"],
        )
        assert "graph" in out
        assert out["graph"]["nodes"]


class TestMemoryGraph:
    def test_bind_creates_graph_edges(self):
        from memory.fabric.relation_engine import MemoryFabricRouter

        r = MemoryFabricRouter()
        r.bind("m1", goal_id="g1", metadata={"session_id": "s-graph"})
        snap = r.graph_snapshot("s-graph")
        assert len(snap["nodes"]) >= 2
        assert len(snap["edges"]) >= 1


class TestGoalEvidenceBinding:
    def test_artifact_trace_binding(self):
        from kernel.goal.goal_evidence_binding import (
            build_goal_evidence_binding,
            merge_binding_into_artifact_trace,
        )
        from kernel.protocol.runtime_contract import ExecutionTrace, RuntimeArtifact

        art = RuntimeArtifact(artifact_id="a1", execution_trace=ExecutionTrace())
        binding = build_goal_evidence_binding(
            root_goal_id="g1", artifact_id="a1", evidence_ids=["e1"]
        )
        merge_binding_into_artifact_trace(art, binding)
        assert art.execution_trace.metadata["goal_evidence_binding"]["evidence_ids"] == ["e1"]


class TestCapabilitySelector:
    def test_rank_data_query(self):
        from kernel.capability_runtime.selector import rank_capabilities_for_intent

        ranked = rank_capabilities_for_intent(
            ["web_search", "data_query"], intent_category="data_query"
        )
        assert ranked[0]["capability_type"] == "data_query"


class TestCapabilityRegistryContract:
    def test_validate_and_metadata(self):
        from kernel.runtime.capability import capability_registry

        v = capability_registry.validate_for_execution("data_query")
        assert isinstance(v, list)
        meta = capability_registry.runtime_metadata("data_query")
        assert "risk_tier" in meta or meta == {}