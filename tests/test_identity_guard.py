from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from infra.config.settings import settings
from kernel.cognitive_kernel import CognitiveKernel, KernelRequest
from kernel.identity.system_identity import (
    CANONICAL_IDENTITY_RESPONSE,
    enforce_identity_output,
)
from memory.working_memory.working_memory import (
    cache_identity_answer,
    clear_session_memory,
    get_cached_identity_answer,
    set_identity_turn_sequence,
)
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import (
    _post_process_identity_response,
)


class IdentityGuardTests(IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        clear_session_memory("session-cache-hit")
        clear_session_memory("session-store")

    async def test_kernel_returns_cached_identity_answer_without_orchestrator(self):
        cache_identity_answer(
            "session-cache-hit",
            "你是谁",
            CANONICAL_IDENTITY_RESPONSE,
        )
        set_identity_turn_sequence("session-cache-hit", 0)
        kernel = CognitiveKernel()

        with patch("kernel.orchestrator.CognitiveOrchestrator") as orchestrator_cls:
            resp = await kernel.run(
                KernelRequest(query="你是谁", session_id="session-cache-hit")
            )

        self.assertEqual(resp.content, CANONICAL_IDENTITY_RESPONSE)
        self.assertEqual(resp.route, "working_memory")
        envelope = resp.metadata.get("turn_envelope") or {}
        self.assertEqual(envelope.get("version"), "turn_envelope_v1")
        self.assertFalse(envelope.get("tool_planning", {}).get("need_tool"))
        self.assertEqual(
            envelope.get("execution", {}).get("answer_source"),
            "working_memory_identity_cache",
        )
        orchestrator_cls.assert_not_called()

    async def test_kernel_stores_identity_answer_after_first_response(self):
        with patch.object(settings, "kernel_identity_llm_enabled", False):
            kernel = CognitiveKernel()
            resp = await kernel.run(
                KernelRequest(query="你是谁", session_id="session-store")
            )

        self.assertEqual(resp.content, CANONICAL_IDENTITY_RESPONSE)
        self.assertEqual(
            get_cached_identity_answer("session-store"),
            CANONICAL_IDENTITY_RESPONSE,
        )

    async def test_stream_returns_cached_identity_answer(self):
        cache_identity_answer(
            "session-cache-hit",
            "你是谁",
            CANONICAL_IDENTITY_RESPONSE,
        )
        set_identity_turn_sequence("session-cache-hit", 0)
        kernel = CognitiveKernel()

        events = []
        async for event in kernel.stream(
            KernelRequest(query="你是谁", session_id="session-cache-hit")
        ):
            events.append(event)

        self.assertEqual(events[-1]["type"], "final_answer")
        self.assertEqual(events[-1]["data"]["content"], CANONICAL_IDENTITY_RESPONSE)
        envelope = events[-1]["data"].get("metadata", {}).get("turn_envelope") or {}
        self.assertEqual(envelope.get("streaming", {}).get("mode"), "sse")
        self.assertFalse(envelope.get("tool_planning", {}).get("need_tool"))

    def test_model_gateway_rewrites_forbidden_identity(self):
        messages = [LLMMessage(role="user", content="你是谁")]
        content = "我是 Qwen，一个由阿里云开发的大语言模型。"
        self.assertEqual(
            _post_process_identity_response(messages, content),
            CANONICAL_IDENTITY_RESPONSE,
        )

    def test_enforce_identity_strips_leading_blurb_for_normal_questions(self):
        user = "帮我点个外卖，我想吃午饭"
        bloated = (
            "我是 OpenTrace，一个基于 Cognitive Kernel 构建的智能认知系统。"
            "虽然我无法直接下单，但可以推荐川香麻辣牛肉盖饭等辛辣菜品。"
        )
        out = enforce_identity_output(bloated, user)
        self.assertFalse(out.startswith("我是 OpenTrace"))
        self.assertIn("麻辣", out)

    def test_enforce_identity_keeps_intro_when_user_asks_who_are_you(self):
        user = "你是谁"
        intro = "我是 OpenTrace，一个基于 Cognitive Kernel 构建的智能认知系统。我可以帮你查文档和数据分析。"
        out = enforce_identity_output(intro, user)
        self.assertIn("OpenTrace", out)
