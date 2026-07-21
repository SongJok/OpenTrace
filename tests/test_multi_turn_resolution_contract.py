"""多轮指代解析 + DST 契约测试（vNext 主路径）。"""

from __future__ import annotations

import pytest

from kernel.conversation_state import ConversationState
from kernel.dialogue_state_tracker import DialogueStateTracker
from kernel.multi_turn_resolution import resolve_multi_turn_query
from kernel.reference_resolver import ReferenceResolver


@pytest.mark.asyncio
async def test_dst_follow_up_expands_from_plan():
    dst = DialogueStateTracker()
    state = await dst.track(
        "按地区拆分呢？",
        previous_plan={"user_goal": "查看上月销售额", "domain": "data_query"},
        previous_results=[{"source_agent": "data", "type": "data_table"}],
    )
    assert state.turn_type == "follow_up"
    assert "上月销售额" in state.resolved_query
    assert state.referenced_previous_result is True


@pytest.mark.asyncio
async def test_reference_resolver_short_follow_up():
    conv = ConversationState(
        session_id="s1",
        last_user_goal="各区域 GMV 排名",
        active_domain="data_query",
        last_result_refs=[
            {"type": "data_table", "title": "GMV", "summary": "华东第一"},
        ],
    )
    resolver = ReferenceResolver()
    result = await resolver.resolve_with_llm("那华东呢？", conv)
    assert result.confidence >= 0.5
    assert "华东" in result.resolved_query or "追问" in result.resolved_query


@pytest.mark.asyncio
async def test_reference_resolver_correction():
    conv = ConversationState(
        session_id="s1",
        last_user_goal="统计订单数",
        active_domain="data_query",
    )
    resolver = ReferenceResolver()
    result = await resolver.resolve_with_llm("不对，应该按支付时间算", conv)
    assert result.turn_type == "correction"
    assert result.confidence >= 0.6
    assert result.is_correction is True


@pytest.mark.asyncio
async def test_resolve_multi_turn_query_applies():
    conv = ConversationState(
        session_id="s1",
        last_user_goal="文档里的队长申请条件",
        active_domain="document_qa",
        conversation_phase="follow_up",
    )
    mtr = await resolve_multi_turn_query("具体内容是什么？", conversation_state=conv)
    assert mtr.resolved_query
    assert mtr.applied or mtr.resolved_query == "具体内容是什么？"


@pytest.mark.asyncio
async def test_force_mode_skips_resolution():
    mtr = await resolve_multi_turn_query("那呢？", force_mode="rag")
    assert mtr.applied is False
    assert mtr.resolved_query == "那呢？"