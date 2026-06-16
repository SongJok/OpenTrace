import asyncio


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


def test_cognitive_kernel_directly_answers_capability_help_without_runtime():
    from kernel.cognitive_kernel import CognitiveKernel, KernelRequest

    async def _run():
        kernel = CognitiveKernel()
        resp = await kernel.run(
            KernelRequest(query="你可以做什么", session_id="s1", user_id="u1")
        )
        assert resp.route == "intent_lock_direct"
        assert resp.intent_category == "capability_help"
        assert "文档" in resp.content
        assert "搜索" in resp.content

    asyncio.run(_run())
