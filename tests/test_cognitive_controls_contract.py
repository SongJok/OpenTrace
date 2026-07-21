import asyncio


def test_hungry_chat_does_not_inherit_data_query_on_follow_up_phase():
    from kernel.cognitive_controls import _detect_follow_up, classify_intent

    assert _detect_follow_up("我饿了", "follow_up") is False
    lock = classify_intent(
        "我饿了",
        prior_intent="data_query",
        conversation_phase="follow_up",
    )
    assert lock.task_type == "general_qa"
    assert "data.query" in lock.disallowed_capabilities
    assert lock.allowed_capabilities == ["model.answer"]


def test_intent_lock_for_capability_help_disables_complex_runtime():
    from kernel.cognitive_controls import classify_intent, direct_answer_for_intent

    lock = classify_intent("你可以做什么")

    assert lock.task_type == "capability_help"
    assert lock.complexity_level == "L0"
    assert "rag.retrieve" in lock.disallowed_capabilities
    assert lock.cognitive_budget.memory_injection is False
    assert lock.cognitive_budget.max_capabilities == 1
    assert direct_answer_for_intent(lock)


def test_relevance_anchor_rejects_unrelated_document_text():
    from kernel.cognitive_controls import passes_relevance_anchor, relevance_score

    text = "狼人杀APP简介：一款线上娱乐社交平台游戏。"

    assert relevance_score("你可以做什么", text) < 0.30
    assert passes_relevance_anchor("你可以做什么", text, threshold=0.30) is False


def test_relevance_anchor_for_captain_procedure_with_routing_prefix():
    from kernel.cognitive_controls import passes_relevance_anchor, relevance_score

    query = "根据文档/知识库，请基于检索内容回答：如何成为队长？"
    text = (
        "队长是狼人杀房间的管理角色，需要满足等级与活跃条件。"
        "申请队长可在个人中心提交，审核通过后即可担任队长。"
    )
    assert relevance_score(query, text) >= 0.30
    assert passes_relevance_anchor(query, text, threshold=0.30) is True


def test_substantive_terms_do_not_inflate_with_every_single_char():
    from kernel.cognitive_controls import _substantive_query_terms

    terms = _substantive_query_terms("如何成为队长")
    assert "队长" in terms
    assert len(terms) < 12


def test_detect_one_sentence_format_under_rag_style_question():
    from kernel.cognitive_controls import detect_response_format_hint

    q = "什么是队长，请你总结成一句话告诉我"
    assert detect_response_format_hint(q) == "one_sentence"


def test_document_qa_not_blocked_by_summary_keywords():
    from kernel.cognitive_controls import classify_intent

    lock = classify_intent("根据知识库，什么是队长，请你总结成一句话告诉我")
    assert lock.task_type == "document_qa"
    assert "rag.retrieve" in lock.allowed_capabilities


def test_strip_user_document_preamble_for_captain_question():
    from kernel.cognitive_controls import (
        _strip_rag_routing_query,
        passes_relevance_anchor,
        relevance_score,
    )

    q = "通过文档信息或者知识库信息，告知我：怎么可以成为队长。"
    stripped = _strip_rag_routing_query(q)
    assert "文档信息" not in stripped or "队长" in stripped
    assert "队长" in stripped
    text = "申请队长可在个人中心提交，审核通过后即可担任队长。"
    assert relevance_score(q, text) >= 0.30
    assert passes_relevance_anchor(q, text, threshold=0.30) is True


def test_rewrite_engine_preserves_protected_simple_intent():
    from kernel.cognitive_controls import apply_intent_lock_to_context, classify_intent
    from kernel.runtime.context import RuntimeContext
    from kernel.runtime.rewrite_engine import RewriteEngine

    async def _run():
        ctx = RuntimeContext(
            request_id="r1",
            session_id="s1",
            user_id="u1",
            query="你可以做什么",
            conversation_history=[{"role": "assistant", "content": "狼人杀APP简介"}],
            memory_context="狼人杀APP简介",
        )
        apply_intent_lock_to_context(ctx, classify_intent(ctx.query))
        result = await RewriteEngine().rewrite(ctx.query, ctx)
        assert result.canonical_query == "你可以做什么"
        assert result.protected_intent == "询问助手能力"
        assert result.rewrite_trace == "intent_lock:protected_simple"

    asyncio.run(_run())


def test_runtime_context_exports_intent_lock_metadata():
    from kernel.cognitive_controls import apply_intent_lock_to_context, classify_intent
    from kernel.runtime.context import RuntimeContext

    ctx = RuntimeContext(request_id="r1", session_id="s1", user_id="u1", query="怎么帮我")
    apply_intent_lock_to_context(ctx, classify_intent(ctx.query))
    metadata = ctx.to_metadata_dict()

    assert metadata["raw_user_query"] == "怎么帮我"
    assert metadata["task_type"] == "capability_help"
    assert metadata["cognitive_budget"]["memory_injection"] is False


def test_cognitive_kernel_sends_capability_help_to_model_runtime(monkeypatch):
    from kernel.cognitive_kernel import CognitiveKernel, KernelRequest, KernelResponse

    class _Gateway:
        async def run(self, request):
            assert request.metadata["model_required"] is True
            return KernelResponse(
                content="模型生成的能力说明",
                session_id=request.session_id,
                route="cognitive_runtime_v2",
                intent_category="capability_help",
                metadata={"model_call_count": 1},
            )

    monkeypatch.setattr("kernel.runtime_gateway.get_runtime_gateway", lambda: _Gateway())

    async def _run():
        kernel = CognitiveKernel()
        resp = await kernel.run(
            KernelRequest(query="你可以做什么", session_id="s1", user_id="u1")
        )
        assert resp.route == "cognitive_runtime_v2"
        assert resp.intent_category == "capability_help"
        assert resp.content == "模型生成的能力说明"
        envelope = resp.metadata.get("turn_envelope") or {}
        assert envelope.get("version") == "turn_envelope_v1"
        assert envelope.get("tool_planning", {}).get("need_tool") is False
        assert envelope.get("execution", {}).get("path") == "runtime_gateway"
        assert envelope.get("finalize", {}).get("stop_reason") == "runtime_completed"

    asyncio.run(_run())
