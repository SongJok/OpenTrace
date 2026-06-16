"""OpenTrace 认知 OS vNext — 架构契约测试。"""

from __future__ import annotations

import pytest


class TestRuntimeContract:
    def test_goal_graph_first_class(self):
        from kernel.protocol.runtime_contract import Goal, GoalGraph

        g = Goal(goal_id="g1", description="analyze sales")
        graph = GoalGraph(root_goal_id="g1", goals=[g], protected_intent="analyze sales")
        d = graph.to_dict()
        assert d["root_goal_id"] == "g1"
        assert len(d["goals"]) == 1

    def test_runtime_task_from_gateway_helper(self):
        from kernel.cognitive_kernel import KernelRequest
        from kernel.runtime_gateway import runtime_task_from_request

        req = KernelRequest(
            query="统计销量",
            session_id="s1",
            metadata={
                "request_id": "r1",
                "intent_lock": {
                    "protected_intent": "统计销量",
                    "task_type": "data_query",
                },
            },
        )
        task = runtime_task_from_request(req)
        assert task.id == "r1"
        assert task.goal_graph is not None
        assert task.goal_graph.intent_category == "data_query"

    def test_goal_planner_subgoals_on_request(self):
        from kernel.cognitive_kernel import KernelRequest
        from kernel.cognition.planner_facade import get_goal_planner
        from kernel.runtime_gateway import runtime_task_from_request

        req = KernelRequest(
            query="A？B？",
            session_id="s1",
            metadata={
                "request_id": "r2",
                "intent_lock": {"protected_intent": "A？B？", "task_type": "general_qa"},
                "sub_questions": [
                    {"text": "问题一", "domain": "web_search"},
                    {"text": "问题二", "domain": "data_query"},
                ],
            },
        )
        graph = get_goal_planner().build_from_request(req)
        assert len(graph.goals) == 3
        task = runtime_task_from_request(req)
        assert len(task.goal_graph.goals) == 3


class TestExecutionPlannerFacade:
    def test_execution_planner_import(self):
        from kernel.cognition.planner_facade import ExecutionPlanner

        assert ExecutionPlanner is not None


class TestGovernanceCenter:
    def test_runtime_governor_rejects_empty_goal(self):
        from kernel.governance.runtime_governor import RuntimeGovernor
        from kernel.protocol.runtime_contract import Goal, RuntimeTask

        task = RuntimeTask(id="t1", goal=Goal(goal_id="g1", description=""))
        result = RuntimeGovernor().evaluate_task(task)
        assert result.allowed is False
        assert "missing_goal" in result.violations

    def test_capability_governor_allowlist(self):
        from kernel.governance.capability_governor import CapabilityGovernor
        from kernel.protocol.runtime_contract import CapabilityRef, Constraints

        gov = CapabilityGovernor()
        c = CapabilityRef(capability_type="rag")
        constraints = Constraints(allowed_capabilities=["data_query"])
        r = gov.check(c, constraints)
        assert r.allowed is False
        assert "rag" in r.denied

    def test_audit_semantic_observability(self):
        from kernel.governance.audit_governor import AuditGovernor

        snap = AuditGovernor().capture_turn(
            route="cognitive_runtime_v2",
            evidence_count=2,
            critic_passed=True,
            hallucination_risk=0.1,
        )
        assert snap.evidence_integrity == 1.0
        assert snap.hallucination_risk == 0.1


class TestProtocolLayer:
    def test_cognition_protocol_envelope(self):
        from kernel.protocol.cognition_protocol import CognitionEnvelope, CognitionPhase

        env = CognitionEnvelope(
            phase=CognitionPhase.PLAN,
            session_id="s",
            request_id="r",
        )
        assert env.version == "cognition_protocol_v1"

    def test_runtime_protocol_execution_unit(self):
        from kernel.protocol.runtime_protocol import ExecutionUnitRef

        u = ExecutionUnitRef(unit_id="u1", capability_type="data_query")
        assert u.capability_type == "data_query"


class TestV4Deprecated:
    def test_orchestrator_v4_module_documents_deprecation(self):
        import kernel.orchestrator_v4 as m

        doc = m.__doc__ or ""
        assert "DEPRECATED" in doc or "已弃用" in doc

    def test_v4_disabled_by_default(self):
        from infra.config.settings import settings

        assert settings.kernel_orchestrator_v4_enabled is False


class TestAlignmentDoc:
    def test_vnext_alignment_doc_exists(self):
        from pathlib import Path

        p = Path(__file__).resolve().parents[1] / "docs/architecture/vnext_alignment.md"
        assert p.is_file()
        text = p.read_text(encoding="utf-8")
        assert "Runtime V2" in text
        assert "force_mode" in text

    def test_orchestrator_v4_disabled_by_default(self):
        from infra.config.settings import settings

        assert settings.kernel_orchestrator_v4_enabled is False
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4

        with pytest.raises(RuntimeError, match="disabled"):
            CognitiveOrchestratorV4()


class TestRefinementPlanner:
    @pytest.mark.asyncio
    async def test_no_failure_no_replan(self):
        from kernel.cognition.planner_facade import RefinementPlanner

        class Ok:
            status = "ok"

        plan, results, replanned, refined = await RefinementPlanner().maybe_replan_after_failures(
            "q", object(), [Ok()]
        )
        assert replanned is False
        assert refined is None


class TestPlannerFacade:
    def test_goal_planner_builds_graph(self):
        from kernel.cognition.planner_facade import GoalPlanner

        graph = GoalPlanner().build_from_intent_lock(
            "统计销量",
            {"protected_intent": "统计销量", "task_type": "data_query"},
            "req-1",
        )
        assert graph.root_goal_id == "req-1"
        assert graph.intent_category == "data_query"