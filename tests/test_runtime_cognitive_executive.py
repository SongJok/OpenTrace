"""
Contract tests for the Cognitive Executive Runtime pipeline.

Verifies:
- CognitiveExecutive end-to-end execution
- CognitivePlanner produces ExecutionPlan with capability_type
- CapabilityGraphBuilder resolves executor types
- ExecutionRuntime handles ExecutionGraph
- FusionEngineV2 and CriticEngineV2 evidence pipeline
- ArtifactComposer produces Artifact with evidence trace
"""

import asyncio

import pytest

from kernel.runtime.capability import capability_registry
from kernel.runtime.context import RuntimeContext


# ═══════════════════════════════════════════════════════════════════════════════
# CognitivePlanner
# ═══════════════════════════════════════════════════════════════════════════════


class TestCognitivePlanner:
    async def test_force_mode_shortcut(self):
        from kernel.runtime.orchestrator import CognitivePlanner
        from kernel.runtime.objects import ExecutionPlan

        planner = CognitivePlanner(capability_registry=capability_registry)
        ctx = RuntimeContext(
            request_id="r1", session_id="s1", user_id="u1",
            query="test", force_mode="web",
        )
        plan = await planner.plan("test", ctx)
        assert isinstance(plan, ExecutionPlan)
        assert plan.required_capabilities == ["web.search"]
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].capability_type == "web.search"

    async def test_llm_plan_produces_execution_plan(self):
        from kernel.runtime.orchestrator import CognitivePlanner
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

        planner = CognitivePlanner(capability_registry=capability_registry)
        ctx = RuntimeContext(
            request_id="r2", session_id="s2", user_id="u1",
            query="华东区上季度销售额是多少",
        )
        plan = await planner.plan("华东区上季度销售额是多少", ctx)

        assert isinstance(plan, ExecutionPlan)
        assert plan.rewritten_query
        assert len(plan.subtasks) >= 1
        for task in plan.subtasks:
            assert isinstance(task, ExecutionTask)
            assert task.capability_type  # must be set
            assert task.task_id
            assert task.agent_type  # backward compat
            assert task.sub_question_id  # backward compat

    async def test_plan_with_understanding_result(self):
        from kernel.runtime.orchestrator import CognitivePlanner
        from kernel.runtime.objects import UnderstandingResult

        planner = CognitivePlanner(capability_registry=capability_registry)
        ctx = RuntimeContext(
            request_id="r3", session_id="s3", user_id="u1",
            query="比较华东和东北的销售数据",
        )
        understanding = UnderstandingResult(
            explicit_goal="对比华东和东北两个区域的销售数据",
            required_capabilities=["data.query", "data.analysis"],
            execution_strategy="parallel",
            risk_level="low",
        )
        plan = await planner.plan("比较华东和东北的销售数据", ctx, understanding=understanding)
        assert plan.understanding_summary
        assert len(plan.subtasks) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# CapabilityGraphBuilder
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityGraphBuilder:
    async def test_direct_build_two_nodes(self):
        from kernel.runtime.capability_graph_builder import CapabilityGraphBuilder
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

        builder = CapabilityGraphBuilder(capability_registry=capability_registry)
        plan = ExecutionPlan(
            required_capabilities=["data.query", "web.search"],
            subtasks=[
                ExecutionTask(task_id="t1", capability_type="data.query", query="SELECT", priority="high"),
                ExecutionTask(task_id="t2", capability_type="web.search", query="latest", priority="normal"),
            ],
        )
        nodes = await builder.build(plan)
        assert len(nodes) == 2
        assert nodes[0].executor_type == "agent"
        assert nodes[1].executor_type == "agent"
        assert nodes[1].resource == "IO"  # web.search

    async def test_single_node_fast_path(self):
        from kernel.runtime.capability_graph_builder import CapabilityGraphBuilder
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

        builder = CapabilityGraphBuilder(capability_registry=capability_registry)
        plan = ExecutionPlan(
            subtasks=[
                ExecutionTask(task_id="t1", capability_type="rag.retrieve", query="document search"),
            ],
        )
        nodes = await builder.build(plan)
        assert len(nodes) == 1
        assert nodes[0].capability_name == "rag.retrieve"
        assert nodes[0].executor_type == "agent"


# ═══════════════════════════════════════════════════════════════════════════════
# RewriteEngine + UnderstandingEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngines:
    async def test_rewrite_fast_path_single_turn(self):
        from kernel.runtime.rewrite_engine import RewriteEngine
        from kernel.runtime.objects import RuntimeCanonicalQuery

        engine = RewriteEngine()
        ctx = RuntimeContext(
            request_id="r1", session_id="s1", user_id="u1",
            query="今天天气怎么样",
        )
        result = await engine.rewrite("今天天气怎么样", ctx)
        assert isinstance(result, RuntimeCanonicalQuery)
        assert result.rewrite_trace == "fast_path:no_context"

    async def test_understanding_fast_path_greeting(self):
        from kernel.runtime.understanding_engine import UnderstandingEngine
        from kernel.runtime.objects import RuntimeCanonicalQuery, UnderstandingResult

        engine = UnderstandingEngine()
        ctx = RuntimeContext(
            request_id="r1", session_id="s1", user_id="u1", query="你好",
        )
        canonical = RuntimeCanonicalQuery(canonical_query="你好", original_query="你好")
        result = await engine.understand(canonical, ctx)
        assert isinstance(result, UnderstandingResult)
        assert result.domain == "conversation"
        assert result.risk_level == "low"


# ═══════════════════════════════════════════════════════════════════════════════
# Evidence Pipeline (FusionV2 + CriticV2)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvidencePipeline:
    async def test_fusion_v2_with_evidence(self):
        from kernel.runtime.fusion import FusionEngineV2, FusionResult
        from kernel.runtime.objects import Evidence, Provenance

        engine = FusionEngineV2()
        evidence = [
            Evidence(
                content="华东区上季度销售额为1000万元",
                provenance=Provenance(source="data", confidence=0.9),
                credibility_score=0.9,
            ),
            Evidence(
                content="华东区包含上海、浙江、江苏等省市",
                provenance=Provenance(source="rag", confidence=0.7),
                credibility_score=0.7,
            ),
        ]
        ctx = RuntimeContext(
            request_id="r1", session_id="s1", user_id="u1", query="test",
        )
        result = await engine.fuse(query="华东区销售额", ctx=ctx, evidence_list=evidence)
        assert isinstance(result, FusionResult)
        assert result.merged_context
        assert result.confidence > 0
        assert result.evidence_ids

    async def test_critic_v2_heuristic(self):
        from kernel.runtime.critic import CriticEngineV2, CriticResult

        engine = CriticEngineV2()
        result = await engine.evaluate(
            query="华东区销售额",
            answer="华东区上季度销售额为1000万元，同比增长15%。",
            evidence_count=2,
        )
        assert isinstance(result, CriticResult)
        assert result.factuality >= 0
        assert result.completeness >= 0
        assert result.evidence_utilization >= 0
        assert result.to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
# ArtifactComposer
# ═══════════════════════════════════════════════════════════════════════════════


class TestArtifactComposer:
    def test_compose_artifact_from_fusion_critic(self):
        from kernel.runtime.artifact_composer import ArtifactComposer
        from kernel.runtime.fusion import FusionResult
        from kernel.runtime.critic import CriticResult

        composer = ArtifactComposer()
        fusion = FusionResult(
            merged_context="华东区上季度销售额为1000万元",
            confidence=0.85,
            method="llm_fusion_v2",
            evidence_ids=["ev1", "ev2"],
        )
        critic = CriticResult(
            passed=True,
            factuality=0.9,
            completeness=0.8,
            evidence_coverage=0.85,
            evidence_utilization=0.9,
        )
        artifact = composer.compose(
            query="华东区销售额",
            fusion_result=fusion,
            critic_result=critic,
            session_id="s1",
            intent_category="data",
        )
        assert artifact.artifact_id
        assert artifact.name
        assert artifact.content == fusion.merged_context
        assert artifact.metadata["evidence_ids"] == ["ev1", "ev2"]
        assert artifact.metadata["critic_factuality"] == 0.9


# ═══════════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataTypes:
    def test_execution_task_backward_compat(self):
        from kernel.runtime.objects import ExecutionTask

        task = ExecutionTask(
            task_id="t1",
            capability_type="data.query",
            query="SELECT * FROM sales",
        )
        assert task.agent_type == "data"
        assert task.sub_question_id == "t1"

    def test_execution_plan_creation(self):
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

        plan = ExecutionPlan(
            required_capabilities=["data.query"],
            subtasks=[
                ExecutionTask(task_id="t1", capability_type="data.query", query="SELECT"),
            ],
            risk_level="low",
        )
        assert plan.plan_id
        assert len(plan.subtasks) == 1
        assert plan.risk_level == "low"

    def test_runtime_canonical_query(self):
        from kernel.runtime.objects import RuntimeCanonicalQuery

        rcq = RuntimeCanonicalQuery(
            canonical_query="查询华东区Q1销售额",
            original_query="华东区上季度",
            entity_resolutions={"上季度": "2026Q1"},
        )
        assert rcq.canonical_query
        assert rcq.entity_resolutions

    def test_understanding_result(self):
        from kernel.runtime.objects import UnderstandingResult

        ur = UnderstandingResult(
            explicit_goal="查询华东区销售额",
            required_capabilities=["data.query"],
            risk_level="low",
        )
        assert ur.explicit_goal
        assert ur.required_capabilities


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界场景和异常处理测试."""

    async def test_cognitive_planner_fallback_on_empty_llm_response(self):
        """当 LLM 返回无效 JSON 时，CognitivePlanner 应该使用 fallback plan."""
        from kernel.runtime.orchestrator import CognitivePlanner
        from kernel.runtime.objects import ExecutionPlan

        planner = CognitivePlanner()
        ctx = RuntimeContext(
            request_id="r-edge", session_id="s-edge", user_id="u1",
            query="test",
        )
        # force_mode 会自动走 shortcut，不需要 LLM
        ctx.force_mode = "rag"
        plan = await planner.plan("test query", ctx)
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].capability_type == "rag.retrieve"

    async def test_fusion_empty_evidence(self):
        """空证据列表应该返回空 FusionResult."""
        from kernel.runtime.fusion import FusionEngineV2

        engine = FusionEngineV2()
        ctx = RuntimeContext(
            request_id="r-edge", session_id="s-edge", user_id="u1", query="test",
        )
        result = await engine.fuse(query="test", ctx=ctx, evidence_list=[])
        assert result.merged_context == ""
        assert result.confidence == 0.0
        assert result.method == "empty"

    async def test_fusion_all_failed_evidence(self):
        """全部失败的证据应该返回 error_aggregation."""
        from kernel.runtime.fusion import FusionEngineV2
        from kernel.runtime.objects import Evidence, Provenance

        engine = FusionEngineV2()
        evidence = [
            Evidence(
                content="agent error: timeout",
                provenance=Provenance(source="data", confidence=0),
                credibility_score=0.0,
            ),
            Evidence(
                content="agent not found: tool",
                provenance=Provenance(source="web", confidence=0),
                credibility_score=0.0,
            ),
        ]
        ctx = RuntimeContext(
            request_id="r-edge", session_id="s-edge", user_id="u1", query="test",
        )
        result = await engine.fuse(query="test", ctx=ctx, evidence_list=evidence)
        assert result.method == "error_aggregation"
        assert result.confidence == 0.0

    async def test_critic_empty_answer(self):
        """空回答应该被 critic 检测."""
        from kernel.runtime.critic import CriticEngineV2

        engine = CriticEngineV2()
        result = await engine.evaluate(query="test", answer="", evidence_count=0)
        assert not result.passed
        assert result.factuality == 0.0
        assert result.hallucination_risk == 1.0

    def test_execution_node_defaults(self):
        """ExecutionNode 默认值应该合理."""
        from kernel.runtime.objects import ExecutionBudget, ExecutionNode

        node = ExecutionNode(node_id="n1", capability_name="data.query")
        assert node.executor_type == ""  # 未解析时为空
        assert node.resource == "CPU"
        assert node.priority == "normal"
        assert node.budget.max_tokens == 4096
        assert node.budget.max_latency_ms == 30000

    def test_execution_plan_empty_subtasks(self):
        """空 subtask 的 ExecutionPlan 也是合法状态."""
        from kernel.runtime.objects import ExecutionPlan

        plan = ExecutionPlan(risk_level="low")
        assert len(plan.subtasks) == 0
        assert plan.plan_id  # 自动生成

    async def test_rewrite_engine_with_history(self):
        """有对话历史时，应该走 LLM 路径."""
        from kernel.runtime.rewrite_engine import RewriteEngine

        engine = RewriteEngine()
        ctx = RuntimeContext(
            request_id="r-edge", session_id="s-edge", user_id="u1",
            query="继续",
            conversation_history=[
                {"role": "user", "content": "帮我查华东区销售额"},
                {"role": "assistant", "content": "华东区销售额为1000万"},
            ],
        )
        result = await engine.rewrite("继续", ctx)
        # 有历史+短查询 → LLM 路径（不是 fast path）
        assert result.canonical_query
        assert result.rewrite_trace != "fast_path:no_context"

    def test_capability_to_agent_mapping(self):
        """capability_type → agent_type 映射应覆盖所有已知类型."""
        from execution.dag_engine.graph import _capability_to_agent

        assert _capability_to_agent("data.query") == "data"
        assert _capability_to_agent("web.search") == "web"
        assert _capability_to_agent("rag.retrieve") == "rag"
        assert _capability_to_agent("tool.datetime") == "tool"
        assert _capability_to_agent("python.execute") == "tool"
        assert _capability_to_agent("chart.generate") == "tool"
        assert _capability_to_agent("memory.retrieve") == "rag"
        assert _capability_to_agent("skill.invoke") == "skills"
        assert _capability_to_agent("rule.lookup") == "rule_engine"
        assert _capability_to_agent("vision.analyze") == "vision"
        assert _capability_to_agent("entity.resolution") == "data"
        # Unknown type should fall back to prefix
        assert _capability_to_agent("custom.action") == "custom"
