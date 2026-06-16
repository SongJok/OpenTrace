"""P1-A 实现后 V5 路由层组件契约测试。"""

import asyncio
import unittest


class TestComplexityEngine:
    """Contract: ComplexityEngine correctly routes queries by complexity."""

    def test_greeting_is_l0(self):
        from kernel.complexity_engine import ComplexityEngine
        engine = ComplexityEngine()
        r = engine.assess("你好")
        assert r.recommended_pipeline == "L0"
        assert r.level == "simple"

    def test_short_factual_is_l0_or_l1(self):
        from kernel.complexity_engine import ComplexityEngine
        engine = ComplexityEngine()
        r = engine.assess("什么是机器学习")
        assert r.recommended_pipeline in ("L0", "L1")

    def test_complex_comparison_is_v4(self):
        from kernel.complexity_engine import ComplexityEngine
        engine = ComplexityEngine()
        r = engine.assess("对比华东和华南的销售数据并分析趋势给出优化建议")
        assert r.recommended_pipeline == "v4"

    def test_empty_query_is_l0(self):
        from kernel.complexity_engine import ComplexityEngine
        engine = ComplexityEngine()
        r = engine.assess("")
        assert r.recommended_pipeline == "L0"
        assert r.score == 0.0

    def test_has_score_field(self):
        from kernel.complexity_engine import ComplexityEngine
        engine = ComplexityEngine()
        r = engine.assess("test query")
        assert 0.0 <= r.score <= 1.0


class TestTinyRouter:
    """Contract: TinyRouter classifies and optionally answers queries."""

    def test_greeting_fast_path(self):
        from kernel.tiny_router import TinyRouter

        async def _run():
            router = TinyRouter()
            r = await router.route("你好")
            assert r.route == "simple"
            assert r.answer is not None
            assert r.difficulty == "simple"
            assert r.metadata.get("method") == "rule"

        asyncio.run(_run())

    def test_identity_query_falls_through(self):
        from kernel.tiny_router import TinyRouter

        async def _run():
            router = TinyRouter()
            r = await router.route("你是谁")
            assert r.route == "complex"
            assert r.answer is None

        asyncio.run(_run())

    def test_empty_query_returns_simple(self):
        from kernel.tiny_router import TinyRouter

        async def _run():
            router = TinyRouter()
            r = await router.route("")
            assert r.route == "simple"
            assert r.answer == ""

        asyncio.run(_run())

    def test_result_has_required_fields(self):
        from kernel.tiny_router import TinyRouter

        async def _run():
            router = TinyRouter()
            r = await router.route("什么是量子计算")
            assert hasattr(r, "route")
            assert hasattr(r, "answer")
            assert hasattr(r, "difficulty")
            assert hasattr(r, "metadata")
            assert isinstance(r.metadata, dict)

        asyncio.run(_run())


class TestSemanticCache:
    """Contract: SemanticCache stores and retrieves by semantic similarity."""

    def test_cache_miss_on_empty(self):
        from kernel.semantic_cache import SemanticCache
        import tempfile, os

        async def _run():
            d = tempfile.mkdtemp()
            try:
                cache = SemanticCache(cache_dir=d, threshold=0.99)
                r = await cache.lookup("test query")
                assert r is None
            finally:
                import shutil
                shutil.rmtree(d, ignore_errors=True)

        asyncio.run(_run())

    def test_cache_hit_after_store(self):
        from kernel.semantic_cache import SemanticCache
        import tempfile

        async def _run():
            d = tempfile.mkdtemp()
            try:
                cache = SemanticCache(cache_dir=d, threshold=0.0)
                await cache.store("test query", "test answer")
                r = await cache.lookup("test query")
                assert r is not None
                assert r.answer == "test answer"
                assert r.hit_count == 1
            finally:
                import shutil
                shutil.rmtree(d, ignore_errors=True)

        asyncio.run(_run())

    def test_empty_query_returns_none(self):
        from kernel.semantic_cache import SemanticCache

        async def _run():
            cache = SemanticCache()
            r = await cache.lookup("")
            assert r is None

        asyncio.run(_run())

    def test_empty_store_does_nothing(self):
        from kernel.semantic_cache import SemanticCache

        async def _run():
            cache = SemanticCache()
            await cache.store("", "")
            # Should not raise

        asyncio.run(_run())


class TestL0RuleRouter:
    """Contract: L0RuleRouter handles identity, greeting, FAQ, and slash commands at zero-LLM latency."""

    def test_identity_query_returns_canonical_hit(self):
        from kernel.query_router_v2 import L0RuleRouter
        from kernel.identity.system_identity import CANONICAL_IDENTITY_RESPONSE

        async def _run():
            router = L0RuleRouter()
            r = await router.route("你是谁")
            assert r.hit is True
            assert r.route == "identity"
            assert r.answer == CANONICAL_IDENTITY_RESPONSE

        asyncio.run(_run())

    def test_identity_query_variant(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("你是什么模型")
            assert r.hit is True
            assert r.route == "identity"
            assert r.answer is not None

        asyncio.run(_run())

    def test_greeting_returns_faq_hit(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("你好")
            assert r.hit is True
            assert r.route == "faq"
            assert r.answer is not None
            assert "OpenTrace" in r.answer

        asyncio.run(_run())

    def test_greeting_variants(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            for q in ["Hi", "Hello", "早上好", "晚上好"]:
                r = await router.route(q)
                assert r.hit is True, f"Expected hit for '{q}'"
                assert r.route == "faq", f"Expected faq route for '{q}'"

        asyncio.run(_run())

    def test_faq_what_can_you_do(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            for q in ["你能做什么", "你可以做什么", "怎么帮我", "你有哪些功能"]:
                r = await router.route(q)
                assert r.hit is True, f"Expected L0 hit for {q}"
                assert r.route == "faq"
                assert len(r.answer) > 20

        asyncio.run(_run())

    def test_faq_help(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("帮助")
            assert r.hit is True
            assert r.route == "faq"
            assert len(r.answer) > 0

        asyncio.run(_run())

    def test_slash_rag_command(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("/rag 查询文档内容")
            assert r.hit is True
            assert r.route == "force_mode"
            assert r.force_mode == "rag"
            assert r.answer == "查询文档内容"

        asyncio.run(_run())

    def test_slash_data_command(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("/data 查询销售订单")
            assert r.hit is True
            assert r.route == "force_mode"
            assert r.force_mode == "data_query"
            assert r.answer == "查询销售订单"

        asyncio.run(_run())

    def test_slash_web_command(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("/web 最新新闻")
            assert r.hit is True
            assert r.route == "force_mode"
            assert r.force_mode == "web"
            assert r.answer == "最新新闻"

        asyncio.run(_run())

    def test_normal_query_no_hit(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("分析华东地区的销售趋势")
            assert r.hit is False
            assert r.route == "v4"
            assert r.answer is None

        asyncio.run(_run())

    def test_empty_query_returns_hit_with_empty_answer(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("")
            assert r.hit is True
            assert r.answer == ""

        asyncio.run(_run())

    def test_force_mode_in_metadata(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("/skills 异常追踪")
            assert r.hit is True
            assert r.route == "force_mode"
            assert r.force_mode == "skills"
            assert r.metadata.get("method") == "slash_command"

        asyncio.run(_run())

    def test_identity_has_method_in_metadata(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("你是谁")
            assert r.metadata.get("method") == "rule"

        asyncio.run(_run())

    def test_weather_query_force_tool_mode(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            for q in ["今天天气怎么样？", "北京明天会下雨吗", "What's the weather in Shanghai?"]:
                r = await router.route(q)
                assert r.hit is True, f"Expected L0 hit for {q!r}"
                assert r.route == "force_mode", f"Expected force_mode for {q!r}"
                assert r.force_mode == "tool", f"Expected tool for {q!r}"
                assert r.metadata.get("category") == "weather"

        asyncio.run(_run())

    def test_time_query_force_tool_mode(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("现在几点了")
            assert r.hit is True
            assert r.route == "force_mode"
            assert r.force_mode == "tool"
            assert r.metadata.get("category") == "time"

        asyncio.run(_run())

    def test_weather_not_misrouted_when_multi_question(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            router = L0RuleRouter()
            r = await router.route("今天天气怎么样？", is_multi=True)
            assert r.hit is False

        asyncio.run(_run())


class TestContextAssembler:
    """Contract: ContextAssembler structures conversation context into organized blocks."""

    def test_empty_context_returns_default(self):
        from kernel.context_assembler import ContextAssembler, AssembledContext
        from kernel.turn_context import TurnContext

        async def _run():
            assembler = ContextAssembler()
            tctx = TurnContext()
            result = await assembler.assemble(tctx)
            assert isinstance(result, AssembledContext)
            assert result.compressed is False
            assert result.total_tokens == 0

        asyncio.run(_run())

    def test_none_context_returns_default(self):
        from kernel.context_assembler import ContextAssembler

        async def _run():
            assembler = ContextAssembler()
            result = await assembler.assemble(None)
            assert result.total_tokens == 0

        asyncio.run(_run())

    def test_history_builds_recent_turns(self):
        from kernel.context_assembler import ContextAssembler
        from kernel.turn_context import TurnContext

        async def _run():
            assembler = ContextAssembler()
            tctx = TurnContext(
                query="最新问题",
                recent_history=[
                    {"role": "user", "content": "之前的用户问题"},
                    {"role": "assistant", "content": "之前的助手回答"},
                ],
            )
            result = await assembler.assemble(tctx)
            assert len(result.recent_turns) == 2
            assert result.recent_turns[0]["role"] == "user"
            assert result.total_tokens > 0

        asyncio.run(_run())

    def test_memory_context_builds_block(self):
        from kernel.context_assembler import ContextAssembler
        from kernel.turn_context import TurnContext

        async def _run():
            assembler = ContextAssembler()
            tctx = TurnContext(
                memory_context=[
                    {"content": "记忆片段1", "score": 0.9, "source": "episodic"},
                    {"content": "记忆片段2", "score": 0.7, "source": "semantic"},
                ],
            )
            result = await assembler.assemble(tctx)
            assert len(result.memory_block) > 0
            assert "记忆片段1" in result.memory_block

        asyncio.run(_run())

    def test_attachment_context_builds_block(self):
        from kernel.context_assembler import ContextAssembler
        from kernel.turn_context import TurnContext

        async def _run():
            assembler = ContextAssembler()
            tctx = TurnContext(
                attachment_contexts=[
                    {"name": "报告.pdf", "content": "文档内容摘要..."},
                ],
            )
            result = await assembler.assemble(tctx)
            assert len(result.attachment_block) > 0
            assert "报告.pdf" in result.attachment_block

        asyncio.run(_run())

    def test_conversation_state_builds_block(self):
        from kernel.context_assembler import ContextAssembler
        from kernel.turn_context import TurnContext

        async def _run():
            assembler = ContextAssembler()
            tctx = TurnContext(
                conversation_state={
                    "active_topic": "销售分析",
                    "conversation_phase": "analysis",
                    "conversation_summary": "用户在分析华东销售",
                    "active_entities": ["华东", "Q4"],
                    "state_extension": {"learned_preferences": {"语言": "中文"}},
                },
            )
            result = await assembler.assemble(tctx)
            assert "销售分析" in result.state_block
            assert "华东" in result.state_block

        asyncio.run(_run())

    def test_summary_block_aggregates_all_sections(self):
        from kernel.context_assembler import ContextAssembler
        from kernel.turn_context import TurnContext

        async def _run():
            assembler = ContextAssembler()
            tctx = TurnContext(
                recent_history=[
                    {"role": "user", "content": "测试问题"},
                ],
                memory_context=[{"content": "测试记忆"}],
                attachment_contexts=[{"name": "test.txt", "content": "test"}],
                conversation_state={"active_topic": "测试"},
            )
            result = await assembler.assemble(tctx)
            assert len(result.summary_block) > 0
            assert "最近对话" in result.summary_block or "记忆" in result.summary_block

        asyncio.run(_run())

    def test_large_history_triggers_compression_flag(self):
        from kernel.context_assembler import ContextAssembler
        from kernel.turn_context import TurnContext

        async def _run():
            assembler = ContextAssembler(max_history_tokens=20)
            long_text = "这是一个很长的对话内容。包含大量中文文本信息。" * 20
            tctx = TurnContext(
                recent_history=[
                    {"role": "user", "content": long_text},
                    {"role": "assistant", "content": long_text},
                    {"role": "user", "content": long_text},
                ],
            )
            result = await assembler.assemble(tctx)
            assert result.compressed is True

        asyncio.run(_run())

    def test_memory_injection_query_uses_last_user_turn(self):
        from kernel.context_assembler import ContextAssembler
        from kernel.turn_context import TurnContext

        async def _run():
            assembler = ContextAssembler()
            tctx = TurnContext(
                query="当前问题",
                recent_history=[
                    {"role": "user", "content": "第一次提问"},
                    {"role": "assistant", "content": "第一次回答"},
                    {"role": "user", "content": "第二次提问"},
                ],
            )
            result = await assembler.assemble(tctx)
            assert result.memory_injection_query == "第二次提问"

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
