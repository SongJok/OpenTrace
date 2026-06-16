"""Preference injection, world turn finalize, Data V2 auto-learning contracts."""

from __future__ import annotations

import pytest

from kernel.conversation_state import ConversationState
from kernel.preference_injection import (
    apply_preference_injection_for_turn,
    merge_learned_preference,
)


@pytest.mark.asyncio
async def test_apply_preference_from_conversation_state():
    conv = ConversationState(session_id="s1", learned_preferences={"tone": "简洁"})
    md = await apply_preference_injection_for_turn(
        user_id="u1",
        session_id="s1",
        metadata={},
        conversation_state=conv,
    )
    assert "user_preference_context_block" in md
    assert "简洁" in md["user_preference_context_block"]


def test_merge_learned_preference():
    conv = ConversationState(session_id="s1")
    merge_learned_preference(conv, "chart_type", "bar")
    assert conv.learned_preferences.get("chart_type") == "bar"


@pytest.mark.asyncio
async def test_finalize_world_model_for_turn_minimal():
    from kernel.world_turn_finalize import finalize_world_model_for_turn

    class _Req:
        session_id = "sess-w1"
        user_id = "u1"
        metadata = {"task_type": "data_query", "request_id": "r1"}
        conversation_state = None

    out = await finalize_world_model_for_turn(session_id="sess-w1", request=_Req())
    assert "world_grounding" in out
    assert out["world_grounding"]["user"]["session_id"] == "sess-w1"


def test_runtime_context_metadata_includes_history():
    from kernel.runtime.context import RuntimeContext

    hist = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    ctx = RuntimeContext(
        request_id="r1",
        session_id="s1",
        user_id="u1",
        query="q",
        conversation_history=hist,
    )
    md = ctx.to_metadata_dict()
    assert md.get("history") == hist


def test_context_assembler_state_block_includes_correction():
    from kernel.context_assembler import ContextAssembler
    from kernel.conversation_state import ConversationState

    cs = ConversationState(
        session_id="s1",
        last_user_goal="统计 GMV",
        active_domain="data_query",
        last_turn_type="correction",
        active_constraints={"user_correction": "按支付时间算"},
    )
    block = ContextAssembler()._build_state_block(cs)
    assert "GMV" in block
    assert "支付时间" in block
    assert "correction" in block or "纠正" in block


@pytest.mark.asyncio
async def test_data_v2_auto_learning_pipeline_invoked(monkeypatch):
    from agents.base import AgentResult, TaskMessage
    from agents.data_agent_v2.supervisor import DataAgentV2Supervisor
    from agents.data_agent_v2.types import CognitiveContext

    calls: list[str] = []

    async def fake_feedback(self, task, ctx, feedback):
        calls.append("feedback")
        ctx.learning_signals = {"feedback_type": "like"}
        return ctx

    async def fake_pattern(self, task, ctx, result):
        calls.append("pattern")
        return ctx

    async def fake_knowledge(self, task, ctx):
        calls.append("knowledge")
        return ctx

    monkeypatch.setattr(DataAgentV2Supervisor, "_run_feedback_collector", fake_feedback)
    monkeypatch.setattr(DataAgentV2Supervisor, "_run_pattern_extractor", fake_pattern)
    monkeypatch.setattr(DataAgentV2Supervisor, "_run_knowledge_updater", fake_knowledge)

    sup = DataAgentV2Supervisor()
    ctx = CognitiveContext(query="q", compiled_sql="SELECT 1", execution_error=None)
    task = TaskMessage(task_id="t1", agent_type="data", query="q", params={})
    result = AgentResult(
        task_id="t1",
        agent_type="data",
        status="success",
        content="ok",
        confidence=0.9,
    )
    out = await sup._run_learning_pipeline(task, result, ctx, auto_mode=True)
    assert "feedback" in calls
    assert "knowledge" in calls


@pytest.mark.asyncio
async def test_hydrate_world_model_for_turn_noop():
    from kernel.world_turn_begin import hydrate_world_model_for_turn

    out = await hydrate_world_model_for_turn(session_id="sess-h1", metadata={})
    assert "hydrated" in out