"""Original Cognitive OS requirements vs implementation — regression guards."""

from __future__ import annotations

import inspect

import pytest


class TestRuntimeGatewaySlimContract:
    def test_dispatcher_no_post_prepare_enrichment(self):
        from kernel.runtime import runtime_turn_dispatcher as rtd

        src = inspect.getsource(rtd.RuntimeTurnDispatcher)
        assert "project_from_context" not in src
        assert "project_goal_graph_to_execution_hints" not in src

    def test_supervisor_owns_dispatch_enrichment(self):
        from kernel.cognitive_supervisor import supervisor as sup

        src = inspect.getsource(sup.CognitiveSupervisor.prepare_run)
        assert "apply_dispatch_enrichment" in src

    def test_gateway_no_governance_center(self):
        from kernel import runtime_gateway as rg

        src = inspect.getsource(rg.RuntimeGateway)
        assert "get_governance_center" not in src
        assert "evaluate_turn" not in src
        assert "_build_artifact" not in src

    def test_gateway_uses_runtime_turn_dispatcher(self):
        from kernel import runtime_gateway as rg

        assert "get_runtime_turn_dispatcher" in inspect.getsource(rg.RuntimeGateway.run)
        assert "dispatch_runtime" in inspect.getsource(
            __import__(
                "kernel.runtime.runtime_turn_dispatcher", fromlist=["RuntimeTurnDispatcher"]
            ).RuntimeTurnDispatcher.run_turn
        )

    def test_gateway_delegates_stream(self):
        from kernel import runtime_gateway as rg

        src = inspect.getsource(rg.RuntimeGateway.stream)
        assert "stream_turn" in src or "get_runtime_turn_dispatcher" in src


class TestSupervisorOwnsOutcomes:
    def test_run_outcomes_has_governance(self):
        from kernel.cognitive_supervisor import run_outcomes as ro

        assert "evaluate_executive_turn_governance" in dir(ro)
        assert "executive_result_to_kernel_response" in dir(ro)


class TestVNextDefaults:
    def test_goal_driven_and_strict_defaults(self):
        from infra.config.settings import settings

        assert settings.kernel_goal_driven_dag_enabled is True
        assert settings.kernel_runtime_phase_transition_strict is True
        assert settings.kernel_registry_dispatch_strict is True
        assert settings.kernel_evidence_contract_strict is True

    def test_runtime_grounding_seven_slices(self):
        from kernel.cognition.runtime_grounding import project_from_context

        ctx = type(
            "C",
            (),
            {
                "session_id": "s1",
                "metadata": {
                    "goal_graph": {
                        "root_goal_id": "g1",
                        "intent_category": "data_query",
                        "protected_intent": "x",
                        "goals": [{"goal_id": "g1"}, {"goal_id": "g1:sub:1", "parent_id": "g1"}],
                    }
                },
            },
        )()
        g = project_from_context(ctx)
        d = g.to_dict()
        assert "user" in d and "environment" in d and "capability" in d
        assert d["environment"]["sub_goal_count"] == 1


class TestAgentRuntimeV3Alignment:
    """Planning §2.7 Phase A/B — manifest, evidence path, import boundaries."""

    def test_manifest_bootstrap_is_reduced_to_supported_question_capabilities(self):
        from kernel.agent_runtime.manifest import get_manifest

        m = get_manifest()
        assert set(m.bootstrap_agent_types) == {"production", "data", "config", "rag"}
        assert "web" not in m.bootstrap_agent_types
        assert "rules" not in m.bootstrap_agent_types

    def test_online_processes_do_not_bootstrap_legacy_tools_or_web_agent(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        agents_package = (root / "agents/__init__.py").read_text(encoding="utf-8")
        worker = (root / "agents/worker.py").read_text(encoding="utf-8")
        runner = (root / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")

        assert "WebAgent" not in agents_package
        assert "import tools" not in worker
        assert "import tools" not in runner

    def test_agents_package_no_gateway_imports(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "agents"
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("#"):
                    continue
                assert "gateway.api_gateway" not in s, f"{path.name}: {s[:80]}"

    def test_executor_attaches_evidence(self):
        from kernel.agent_runtime import executor as ex_mod

        assert "attach_evidence_objects" in inspect.getsource(
            ex_mod.AgentRuntimeExecutor.execute_task
        )

    def test_staging_profile_forces_strict_flags(self):
        from infra.config.settings import Settings

        s = Settings(
            app_env="staging",
            kernel_agent_runtime_v3_strict=False,
            kernel_unified_evidence_strict=False,
            gateway_port=14100,
            app_port=14100,
            app_secret_key="test-app-secret",
            jwt_secret="test-jwt-secret",
            data_secret_key="test-data-secret",
            object_storage_backend="local",
        )
        assert s.kernel_agent_runtime_v3_strict is True
        assert s.kernel_unified_evidence_strict is True


class TestLegacyOrchestratorRemoved:
    def test_v4_implementation_and_shims_are_absent(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        assert not (root / "legacy" / "v4" / "orchestrator.py").exists()
        assert not (root / "kernel" / "orchestrator_v4.py").exists()
        assert not (root / "kernel" / "orchestrator.py").exists()


class TestRuntimeRegistry:
    def test_three_runtimes(self):
        from kernel.runtime.registry import ensure_runtimes_registered, list_runtimes

        ensure_runtimes_registered()
        names = list_runtimes()
        assert "cognitive_executive" in names
        assert "data_intelligence" in names
        assert "multi_goal" in names


class TestDataIntelligenceInRepo:
    def test_service_module(self):
        from services.data_intelligence_runtime import run_data_intelligence_turn

        assert callable(run_data_intelligence_turn)


class TestGoalEvidenceTypedField:
    def test_runtime_artifact_binding_field(self):
        from kernel.protocol.runtime_contract import GoalEvidenceBinding, RuntimeArtifact

        b = GoalEvidenceBinding(root_goal_id="g", artifact_id="a", evidence_ids=["e1"])
        art = RuntimeArtifact(artifact_id="a", goal_evidence_binding=b)
        assert art.goal_evidence_binding.evidence_ids == ["e1"]


class TestGoalDrivenPlanning:
    def test_goal_execution_projection_hints(self):
        from kernel.goal.goal_projection import project_goal_graph_to_execution_hints

        hints = project_goal_graph_to_execution_hints(
            {
                "root_goal_id": "r1",
                "intent_category": "data_query",
                "goals": [
                    {"goal_id": "r1", "parent_id": None},
                    {
                        "goal_id": "r1:sub:1",
                        "parent_id": "r1",
                        "metadata": {"domain": "web_search"},
                    },
                ],
            }
        )
        assert hints["sub_goal_count"] == 1
        assert hints["parallel_eligible"] is False

    def test_executive_uses_goal_driven_planner(self):
        from kernel.runtime import cognitive_executive as ce

        src = inspect.getsource(ce.CognitiveExecutive.execute)
        assert "plan_from_goal_context" in src
        assert "ExecutionPlanner().plan_and_project" not in src


class TestRegistryDispatchGovernance:
    def test_registry_evaluates_before_handler(self):
        from kernel.runtime.registry_governance import evaluate_registry_dispatch

        class _Req:
            session_id = "s1"
            metadata = {
                "intent_lock": {
                    "allowed_capabilities": ["model.answer"],
                    "disallowed_capabilities": ["data_query"],
                }
            }

        class _Ctx:
            metadata = {}

        gate = evaluate_registry_dispatch("data_intelligence", request=_Req(), ctx=_Ctx())
        assert gate.allowed is False
        assert any("data" in v for v in gate.violations)


class TestMemoryGraphRedis:
    @pytest.mark.asyncio
    async def test_persist_and_hydrate_in_process(self):
        from memory.fabric.memory_graph import (
            MemoryGraphStore,
            _apply_snapshot,
        )

        store = MemoryGraphStore()
        store.upsert_node("m1", "memory", {"x": 1})
        store.link("m1", "g1", relation="bound_to_goal")
        snap = store.to_dict()
        store2 = MemoryGraphStore()
        _apply_snapshot(store2, snap)
        assert "m1" in store2._nodes
        assert len(store2._edges) == 1


class TestMemoryFabricRetrieval:
    def test_goal_scoped_retrieve_after_bind(self):
        from memory.fabric.retrieval import retrieve_goal_scoped_memory
        from memory.fabric.router_singleton import bind_turn_memory

        bind_turn_memory(
            session_id="s-mem",
            request_id="r1",
            goal_id="g1",
            query="销量",
            answer_preview="增长10%",
            route="data_query",
        )
        hits = retrieve_goal_scoped_memory(session_id="s-mem", goal_id="g1", query="销量")
        assert len(hits) >= 1


class TestStrategicPlannerContext:
    def test_project_hints_from_context(self):
        from kernel.cognition.planner_facade import get_strategic_planner

        class _Ctx:
            metadata = {"intent_lock": {"cognitive_budget": {"max_replans": 1}}}
            task_type = "data_query"

        hints = get_strategic_planner().project_hints_from_context(
            _Ctx(),
            {"intent_category": "data_query", "sub_goal_count": 0, "parallel_eligible": False},
        )
        assert hints["preferred_runtime"] in ("data_intelligence", "cognitive_executive")


class TestRuntimeGroundingWorldModel:
    def test_seven_slice_projection(self):
        from kernel.cognition.runtime_grounding import project_from_context

        ctx = type(
            "C",
            (),
            {
                "session_id": "s1",
                "request_id": "r1",
                "allowed_capabilities": ["model.answer"],
                "metadata": {
                    "goal_graph": {
                        "root_goal_id": "g1",
                        "intent_category": "data_query",
                        "goals": [{"goal_id": "g1"}, {"goal_id": "g1:sub:1", "parent_id": "g1"}],
                    },
                    "runtime_phase": "plan",
                },
            },
        )()
        state = project_from_context(ctx)
        d = state.to_dict()
        assert "environment" in d and d["environment"]["sub_goal_count"] == 1
        assert "memory" in d and d["memory"]["goal_id"] == "g1"


class TestBehaviorContractsExtended:
    def test_evidence_and_capability_contracts(self):
        from kernel.protocol.behavior_contracts import (
            validate_capability_execution_contract,
            validate_evidence_contract,
        )

        assert len(validate_evidence_contract([], min_count=1)) >= 1
        assert validate_evidence_contract(["e1"], min_count=1) == []
        assert validate_capability_execution_contract("data.query", ["data.query"], []) == []
        assert "capability_disallowed" in str(
            validate_capability_execution_contract("data.query", ["data.query"], ["data.query"])
        )
        assert validate_capability_execution_contract("data.query", ["model.answer"], [])


class TestReplayContract:
    def test_validate_replay(self):
        from kernel.protocol.behavior_contracts import ReplayContract, validate_replay_contract

        assert "missing_request_id" in validate_replay_contract(ReplayContract("", "s", "g"))
        assert "missing_root_goal_id" in validate_replay_contract(ReplayContract("r", "s", ""))
        assert validate_replay_contract(ReplayContract("r", "s", "g")) == []


class TestGoalEvidenceOnArtifact:
    def test_binding_in_trace(self):
        from kernel.goal.goal_evidence_binding import (
            build_goal_evidence_binding,
            merge_binding_into_artifact_trace,
        )
        from kernel.protocol.runtime_contract import ExecutionTrace, RuntimeArtifact

        art = RuntimeArtifact(artifact_id="a2", execution_trace=ExecutionTrace())
        merge_binding_into_artifact_trace(
            art,
            build_goal_evidence_binding(
                root_goal_id="g2", artifact_id="a2", evidence_ids=["e1", "e2"]
            ),
        )
        assert len(art.execution_trace.metadata["goal_evidence_binding"]["evidence_ids"]) == 2


class TestPhaseTransitionStrict:
    def test_blocked_when_strict_and_violations(self):
        from infra.config.settings import settings
        from kernel.runtime.cognitive_executive import CognitiveExecutive

        ex = CognitiveExecutive()
        ctx = type("C", (), {"metadata": {"phase_transition_violations": ["x"]}})()
        old = settings.kernel_runtime_phase_transition_strict
        try:
            settings.kernel_runtime_phase_transition_strict = True
            assert ex._phase_transition_blocked(ctx) is True
        finally:
            settings.kernel_runtime_phase_transition_strict = old
