"""认知监督层 + 瘦 RuntimeGateway 架构契约测试。"""

from __future__ import annotations

import inspect

import pytest


class TestCognitiveSupervisor:
    def test_prepare_seeds_fabric_graph(self):
        from kernel.cognitive_kernel import KernelRequest
        from kernel.cognitive_supervisor import get_cognitive_supervisor

        req = KernelRequest(
            query="hello",
            session_id="s-fab",
            metadata={
                "request_id": "r-fab",
                "intent_lock": {"protected_intent": "hello", "task_type": "general_qa"},
            },
        )
        prepared = get_cognitive_supervisor().prepare_run(req)
        assert prepared.ctx is not None
        assert (prepared.ctx.metadata or {}).get("fabric_graph_seeded")

    def test_supervisor_prepare_run(self):
        from kernel.cognitive_kernel import KernelRequest
        from kernel.cognitive_supervisor import get_cognitive_supervisor

        req = KernelRequest(
            query="统计销量",
            session_id="s1",
            metadata={
                "request_id": "r-sup",
                "intent_lock": {
                    "protected_intent": "统计销量",
                    "task_type": "data_query",
                },
            },
        )
        prepared = get_cognitive_supervisor().prepare_run(req)
        assert prepared.governance_meta.get("allowed") is True
        assert prepared.runtime_task.goal_graph is not None
        assert prepared.ctx is not None
        assert prepared.goal_graph_dict.get("root_goal_id") == "r-sup"
        flags = (prepared.ctx.metadata or {}).get("effective_runtime_flags")
        assert isinstance(flags, dict)
        assert len(flags) >= 1

    def test_strategy_projection_data_query(self):
        from kernel.cognition.planner_facade import get_strategic_planner
        from kernel.cognitive_kernel import KernelRequest
        from kernel.cognitive_supervisor.prepare_dispatch import runtime_task_from_request

        req = KernelRequest(
            query="查询订单",
            session_id="s1",
            metadata={
                "request_id": "r-data",
                "intent_lock": {"task_type": "data_query"},
            },
        )
        task = runtime_task_from_request(req)
        hints = get_strategic_planner().project_hints(task, req)
        assert hints["preferred_runtime"] in ("data_intelligence", "cognitive_executive")
        assert hints["intent_category"] == "data_query"


class TestRuntimeGatewaySlim:
    def test_gateway_no_goal_planner_import_in_run(self):
        from kernel import runtime_gateway as rg

        src = inspect.getsource(rg.RuntimeGateway.run)
        assert "get_goal_planner" not in src
        assert "run_multi_question" not in src
        assert "get_cognitive_supervisor" in src
        assert "evaluate_turn" not in src
        assert "get_governance_center" not in src

    def test_runtime_registry_lists_runtimes(self):
        from kernel.runtime.registry import ensure_runtimes_registered, list_runtimes

        ensure_runtimes_registered()
        names = list_runtimes()
        assert "cognitive_executive" in names
        assert "data_intelligence" in names
        assert "multi_goal" in names

    def test_goal_lifecycle_state(self):
        from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state
        from kernel.protocol.runtime_contract import Goal

        g = Goal(goal_id="g1", description="test")
        transition_goal_state(g, GoalLifecycleState.PROJECTED)
        assert g.metadata["lifecycle_state"] == "projected"


class TestDataIntelligenceRuntime:
    @pytest.mark.asyncio
    async def test_module_import(self):
        from services.data_intelligence_runtime import run_data_intelligence_turn

        assert callable(run_data_intelligence_turn)


class TestSemanticMetrics:
    def test_cognitive_health_in_governance_bundle(self):
        from kernel.governance.governance_center import get_governance_center

        bundle = get_governance_center().evaluate_turn(
            evidence_count=2,
            fusion_confidence=0.9,
            hallucination_risk=0.1,
            critic_passed=True,
            route="cognitive_runtime_v2",
        )
        assert "cognitive_health" in bundle.semantic_observability
        assert bundle.semantic_observability["cognitive_health"]["evidence_integrity"] >= 0.5


class TestMemoryFabric:
    def test_bind_turn_memory(self):
        from memory.fabric.router_singleton import bind_turn_memory, get_memory_fabric_router

        bind_turn_memory(
            session_id="s1",
            request_id="r1",
            goal_id="g1",
            query="hello",
            answer_preview="world",
            route="test",
        )
        rels = get_memory_fabric_router().query_by_goal("g1")
        assert len(rels) >= 1


class TestGoalRuntimeHooks:
    def test_hooks_from_context(self):
        from kernel.goal.goal_runtime_hooks import GoalRuntimeHooks
        from kernel.protocol.runtime_contract import Goal, GoalGraph, RuntimeTask

        class Ctx:
            request_id = "r1"
            session_id = "s1"
            metadata = {
                "runtime_task": RuntimeTask(
                    id="r1",
                    goal=Goal(goal_id="g1", description="q"),
                    goal_graph=GoalGraph(root_goal_id="g1", goals=[]),
                )
            }

        hooks = GoalRuntimeHooks.from_context(Ctx())
        assert hooks is not None
        hooks.on_phase("plan")


class TestCapabilityGovernance:
    def test_govern_denies_disallowed(self):
        from kernel.protocol.runtime_contract import Constraints, Goal, RuntimeTask
        from kernel.runtime.capability_governance import govern_capabilities_for_plan

        class Ctx:
            metadata = {
                "runtime_task": RuntimeTask(
                    id="r1",
                    goal=Goal(goal_id="g1", description="q"),
                    constraints=Constraints(
                        allowed_capabilities=["model.answer"],
                        disallowed_capabilities=["data.query"],
                    ),
                )
            }

        class Plan:
            subtasks = [type("S", (), {"capability_type": "data.query"})()]

        allowed, denied = govern_capabilities_for_plan(Plan(), None, Ctx())
        assert "data.query" in denied or "data.query" not in allowed

    def test_governance_fallback_node(self):
        from kernel.protocol.runtime_contract import Constraints, Goal, RuntimeTask
        from kernel.runtime.capability_governance import (
            GOVERNANCE_FALLBACK_CAPABILITY,
            apply_governance_with_fallback,
        )

        class Node:
            capability_name = "data.query"
            capability_type = "data.query"

        class Ctx:
            session_id = "s"
            user_id = "u"
            request_id = "r"
            metadata = {
                "runtime_task": RuntimeTask(
                    id="r",
                    goal=Goal(goal_id="g", description="q"),
                    constraints=Constraints(
                        allowed_capabilities=["model.answer"],
                        disallowed_capabilities=["data.query"],
                    ),
                )
            }

        out = apply_governance_with_fallback(None, [Node()], Ctx(), "统计销量")
        assert len(out) == 1
        assert out[0].capability_name == GOVERNANCE_FALLBACK_CAPABILITY
        assert (Ctx.metadata.get("capability_governance") or {}).get("fallback_applied")


class TestGoalProjection:
    def test_world_state_from_graph(self):
        from kernel.goal.goal_projection import project_goal_graph_to_world_state
        from kernel.protocol.runtime_contract import Goal, GoalGraph

        g = GoalGraph(root_goal_id="r", goals=[Goal(goal_id="r", description="root")])
        g.add_goal(Goal(goal_id="r:sub:1", description="sub", parent_id="r", priority=0))
        w = project_goal_graph_to_world_state(g)
        assert w["sub_goal_count"] == 1
        assert w["sub_goals"][0]["goal_id"] == "r:sub:1"


class TestGoalMemoryBinding:
    def test_bind_from_runtime_context(self):
        from kernel.goal.goal_memory_binding import bind_from_runtime_context
        from memory.fabric.router_singleton import get_memory_fabric_router

        class Ctx:
            session_id = "s1"
            request_id = "r1"
            query = "hello"
            metadata = {"goal_graph": {"root_goal_id": "g1"}, "route": "test"}

        bind_from_runtime_context(Ctx(), "answer text")
        assert len(get_memory_fabric_router().query_by_goal("g1")) >= 1


class TestContextFabricGraph:
    def test_build_graph_links_goal_memory(self):
        from kernel.context_fabric_graph import build_fabric_graph_from_turn

        class TC:
            session_id = "s1"
            metadata = {"request_id": "req1"}
            memory_context = [{"content": "past fact", "score": 0.8}]

        g = build_fabric_graph_from_turn(
            TC(), {"root_goal_id": "req1", "intent_category": "general"}
        )
        d = g.to_dict()
        assert len(d["nodes"]) >= 2


class TestMultiGoalScheduler:
    def test_schedule_by_priority(self):
        from kernel.goal.multi_goal_scheduler import schedule_sub_goals_from_graph
        from kernel.protocol.runtime_contract import Goal, GoalGraph

        graph = GoalGraph(root_goal_id="root", goals=[])
        graph.add_goal(Goal(goal_id="root", description="root", parent_id=None))
        graph.add_goal(
            Goal(goal_id="root:sub:2", description="B", parent_id="root", priority=1)
        )
        graph.add_goal(
            Goal(goal_id="root:sub:1", description="A", parent_id="root", priority=0)
        )
        sq = [{"id": "q1", "text": "A"}, {"id": "q2", "text": "B"}]
        ordered = schedule_sub_goals_from_graph(graph, sq)
        assert ordered[0]["text"] == "A"

    def test_dependency_chain(self):
        from kernel.goal.multi_goal_scheduler import apply_goal_dependencies_to_execution_graph

        class Node:
            def __init__(self, nid, sq, order):
                self.node_id = nid
                self.params = {"sub_question_id": sq, "display_order": order}
                self.depends_on = []

        g = [
            Node("n1", "q1", 1),
            Node("n2", "q2", 2),
        ]
        out = apply_goal_dependencies_to_execution_graph(g, sequential_sub_goals=True)
        assert "n1" in (out[1].depends_on or [])

    def test_multi_planner_exports_governance_aggregation_pattern(self):
        """build_multi_execution_graph sets multi_capability_governance on request.metadata."""
        import inspect

        from kernel.cognition import multi_execution_planner as mep

        src = inspect.getsource(mep.build_multi_execution_graph)
        assert "multi_capability_governance" in src
        assert "apply_governance_with_fallback" in src
