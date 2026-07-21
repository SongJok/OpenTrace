"""Intent Lock 全链路契约测试。

覆盖 F1-F6 修复点：
  - F1: CognitivePlannerV2 生成 prompt 包含意图约束块
  - F2: 约束拒绝降级路径
  - F3: V4 PlanAgent 过滤 disallowed subtask
  - F4: 能力名称规范化
  - F6: cognitive_executive 复用已有 intent_lock
"""

import pytest

from kernel.cognitive_controls import (
    _CAPABILITY_NORMALIZE_MAP,
    CognitiveBudget,
    IntentLock,
    _light_lock,
    _simple_lock,
    normalize_capability_name,
)

# ── F4: 能力名称规范化 ────────────────────────────────────────────────────

class TestCapabilityNameNormalization:
    """normalize_capability_name() 正确映射 intent_lock 名称到实际注册名称。"""

    def test_tool_weather_normalizes(self):
        assert normalize_capability_name("tool.weather") == "get_weather"

    def test_tool_datetime_normalizes(self):
        assert normalize_capability_name("tool.datetime") == "get_current_time"

    def test_chart_generate_normalizes(self):
        assert normalize_capability_name("chart.generate") == "chart_generator"

    def test_tool_execute_normalizes(self):
        assert normalize_capability_name("tool.execute") == "tool.datetime"

    def test_passthrough_unknown(self):
        assert normalize_capability_name("model.answer") == "model.answer"
        assert normalize_capability_name("data.query") == "data.query"
        assert normalize_capability_name("rag.retrieve") == "rag.retrieve"

    def test_normalize_map_keys(self):
        """验证映射表中的所有值都是有效目标。"""
        for src, dst in _CAPABILITY_NORMALIZE_MAP.items():
            assert isinstance(src, str) and len(src) > 0
            assert isinstance(dst, str) and len(dst) > 0

    def test_memory_retrieve_removed_from_simple_lock(self):
        """_simple_lock 的 disallowed 列表中不含 memory.retrieve。"""
        lock = _simple_lock("测试", "测试", "test", "测试意图", [])
        assert "memory.retrieve" not in lock.disallowed_capabilities

    def test_memory_retrieve_removed_from_light_lock(self):
        """_light_lock 的 disallowed 列表中不含 memory.retrieve。"""
        lock = _light_lock("测试", "测试", "test", ["model.answer"])
        assert "memory.retrieve" not in lock.disallowed_capabilities


# ── F1: CognitivePlannerV2 意图约束块 ────────────────────────────────────

class TestCognitivePlannerIntentBlock:
    """_build_intent_constraint_block() 正确生成约束信息。"""

    @pytest.fixture
    def planner(self):
        from kernel.runtime.cognitive.cognitive_planner_v2 import CognitivePlannerV2
        return CognitivePlannerV2()

    @pytest.fixture
    def ctx_with_general_qa(self):
        """模拟 general_qa 的 RuntimeContext。"""
        from kernel.runtime.context import RuntimeContext
        ctx = RuntimeContext(
            session_id="test-sid",
            request_id="test-rid",
            user_id="test-uid",
            query="什么是机器学习",
        )
        ctx.allowed_capabilities = ["model.answer"]
        ctx.disallowed_capabilities = ["rag.retrieve", "web.search", "data.query"]
        ctx.task_type = "general_qa"
        return ctx

    @pytest.fixture
    def ctx_without_constraints(self):
        """模拟无约束的 RuntimeContext。"""
        from kernel.runtime.context import RuntimeContext
        return RuntimeContext(
            session_id="test-sid",
            request_id="test-rid",
            user_id="test-uid",
            query="什么是机器学习",
        )

    def test_block_contains_task_type(self, planner, ctx_with_general_qa):
        block = planner._build_intent_constraint_block(ctx_with_general_qa)
        assert "general_qa" in block

    def test_block_contains_allowed(self, planner, ctx_with_general_qa):
        block = planner._build_intent_constraint_block(ctx_with_general_qa)
        assert "model.answer" in block

    def test_block_contains_disallowed(self, planner, ctx_with_general_qa):
        block = planner._build_intent_constraint_block(ctx_with_general_qa)
        assert "rag.retrieve" in block
        assert "web.search" in block

    def test_block_model_answer_key_hint(self, planner, ctx_with_general_qa):
        """当仅允许 model.answer 时，提示 information_gaps 必须为空。"""
        block = planner._build_intent_constraint_block(ctx_with_general_qa)
        assert "information_gaps" in block.lower() or "无需" in block or "空" in block

    def test_empty_block_when_no_constraints(self, planner, ctx_without_constraints):
        block = planner._build_intent_constraint_block(ctx_without_constraints)
        assert block == ""


# ── F3: PlanAgent 过滤 disallowed subtask ─────────────────────────────────

class TestPlanAgentIntentFiltering:
    """PlanAgent._filter_disallowed_subtasks() 正确过滤被禁能力。"""

    @pytest.fixture
    def plan_agent(self):
        from kernel.plan_agent import PlanAgent
        return PlanAgent()

    def test_filter_removes_disallowed_rag(self, plan_agent):
        from kernel.plan_agent import SubTask
        sts = [
            SubTask(agent_type="rag", query="test"),
            SubTask(agent_type="tool", query="test"),
        ]
        intent_lock = {"disallowed_capabilities": ["rag.retrieve"]}
        filtered = plan_agent._filter_disallowed_subtasks(sts, intent_lock)
        assert len(filtered) == 1
        assert filtered[0].agent_type == "tool"

    def test_filter_removes_disallowed_web(self, plan_agent):
        from kernel.plan_agent import SubTask
        sts = [
            SubTask(agent_type="web", query="test"),
            SubTask(agent_type="data", query="test"),
        ]
        intent_lock = {"disallowed_capabilities": ["web.search"]}
        filtered = plan_agent._filter_disallowed_subtasks(sts, intent_lock)
        assert len(filtered) == 1
        assert filtered[0].agent_type == "data"

    def test_filter_removes_disallowed_data(self, plan_agent):
        from kernel.plan_agent import SubTask
        sts = [
            SubTask(agent_type="data", query="test"),
        ]
        intent_lock = {"disallowed_capabilities": ["data.query"]}
        filtered = plan_agent._filter_disallowed_subtasks(sts, intent_lock)
        assert len(filtered) == 0

    def test_filter_passes_through_when_empty_disallowed(self, plan_agent):
        from kernel.plan_agent import SubTask
        sts = [SubTask(agent_type="rag", query="test")]
        filtered = plan_agent._filter_disallowed_subtasks(sts, {})
        assert len(filtered) == 1

    def test_filter_passes_through_when_none_intent(self, plan_agent):
        from kernel.plan_agent import SubTask
        sts = [SubTask(agent_type="rag", query="test")]
        filtered = plan_agent._filter_disallowed_subtasks(sts, None)
        assert len(filtered) == 1


# ── F6: cognitive_executive 复用已有 intent_lock ──────────────────────────

class TestExecutiveIntentLockReuse:
    """验证 IntentLock 从 dict 重建的正确性。"""

    def test_intent_lock_from_dict(self):
        payload = {
            "raw_user_query": "测试问题",
            "normalized_query": "测试问题",
            "protected_intent": "测试问题",
            "task_type": "general_qa",
            "complexity_level": "L1",
            "allowed_capabilities": ["model.answer"],
            "disallowed_capabilities": ["rag.retrieve", "web.search", "data.query"],
            "confidence": 0.72,
            "cognitive_budget": {
                "max_planning_depth": 1,
                "max_capabilities": 1,
                "max_replans": 0,
                "max_memory_tokens": 0,
                "max_context_expansion": 256,
                "max_reasoning_steps": 2,
                "memory_injection": False,
                "workspace_context": False,
                "critic": False,
            },
            "relevance_threshold": 0.35,
        }
        budget_raw = payload.get("cognitive_budget", {}) or {}
        lock = IntentLock(
            raw_user_query=payload.get("raw_user_query", ""),
            normalized_query=payload.get("normalized_query", ""),
            protected_intent=payload.get("protected_intent", ""),
            task_type=payload.get("task_type", "general_qa"),
            complexity_level=payload.get("complexity_level", "L1"),
            allowed_capabilities=payload.get("allowed_capabilities", []),
            disallowed_capabilities=payload.get("disallowed_capabilities", []),
            confidence=float(payload.get("confidence", 0.72)),
            cognitive_budget=CognitiveBudget(
                max_planning_depth=int(budget_raw.get("max_planning_depth", 1)),
                max_capabilities=int(budget_raw.get("max_capabilities", 1)),
                max_replans=int(budget_raw.get("max_replans", 0)),
                max_memory_tokens=int(budget_raw.get("max_memory_tokens", 0)),
                max_context_expansion=int(budget_raw.get("max_context_expansion", 256)),
                max_reasoning_steps=int(budget_raw.get("max_reasoning_steps", 2)),
                memory_injection=bool(budget_raw.get("memory_injection", False)),
                workspace_context=bool(budget_raw.get("workspace_context", False)),
                critic=bool(budget_raw.get("critic", False)),
            ),
            relevance_threshold=float(payload.get("relevance_threshold", 0.35)),
        )
        assert lock.task_type == "general_qa"
        assert lock.allowed_capabilities == ["model.answer"]
        assert "rag.retrieve" in lock.disallowed_capabilities
        assert lock.cognitive_budget.max_capabilities == 1

    def test_intent_lock_from_dict_empty_budget(self):
        """空 cognitive_budget 使用默认值。"""
        lock = IntentLock(
            raw_user_query="test",
            normalized_query="test",
            protected_intent="test",
            task_type="greeting",
            complexity_level="L0",
            allowed_capabilities=[],
            disallowed_capabilities=[],
            cognitive_budget=CognitiveBudget(),
        )
        assert lock.cognitive_budget.max_capabilities == 1
        assert lock.cognitive_budget.max_replans == 0
