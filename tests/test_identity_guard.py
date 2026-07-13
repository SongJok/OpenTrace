from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from kernel.cognitive_kernel import CognitiveKernel, KernelRequest
from kernel.cognitive_kernel import KernelResponse
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

    @staticmethod
    def _runtime_gateway(content: str):
        class _Gateway:
            def __init__(self) -> None:
                self.calls = 0

            async def run(self, request):
                self.calls += 1
                assert request.metadata["model_required"] is True
                return KernelResponse(
                    content=content,
                    session_id=request.session_id,
                    route="cognitive_runtime_v2",
                    intent_category="identity",
                    metadata={"model_call_count": 1, "model_call_id": "mc_identity"},
                )

            async def stream(self, request):
                self.calls += 1
                assert request.metadata["model_required"] is True
                yield {
                    "type": "final_answer",
                    "data": {
                        "content": content,
                        "route": "cognitive_runtime_v2",
                        "metadata": {"model_call_count": 1, "model_call_id": "mc_identity"},
                    },
                }

        return _Gateway()

    async def test_kernel_identity_cache_is_context_not_a_direct_answer(self):
        cache_identity_answer(
            "session-cache-hit",
            "你是谁",
            CANONICAL_IDENTITY_RESPONSE,
        )
        set_identity_turn_sequence("session-cache-hit", 0)
        gateway = self._runtime_gateway("模型生成的身份回答")
        kernel = CognitiveKernel()

        with patch("kernel.runtime_gateway.get_runtime_gateway", return_value=gateway):
            resp = await kernel.run(
                KernelRequest(query="你是谁", session_id="session-cache-hit")
            )

        self.assertEqual(resp.content, "模型生成的身份回答")
        self.assertEqual(resp.route, "cognitive_runtime_v2")
        self.assertEqual(gateway.calls, 1)
        envelope = resp.metadata.get("turn_envelope") or {}
        self.assertEqual(envelope.get("version"), "turn_envelope_v1")
        self.assertFalse(envelope.get("tool_planning", {}).get("need_tool"))
        self.assertEqual(
            envelope.get("execution", {}).get("answer_source"),
            "cognitive_runtime",
        )

    async def test_kernel_stores_identity_answer_after_first_response(self):
        gateway = self._runtime_gateway(CANONICAL_IDENTITY_RESPONSE)
        with patch("kernel.runtime_gateway.get_runtime_gateway", return_value=gateway):
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
        gateway = self._runtime_gateway("模型生成的流式身份回答")
        kernel = CognitiveKernel()

        events = []
        with patch("kernel.runtime_gateway.get_runtime_gateway", return_value=gateway):
            async for event in kernel.stream(
                KernelRequest(query="你是谁", session_id="session-cache-hit")
            ):
                events.append(event)

        self.assertEqual(events[-1]["type"], "final_answer")
        self.assertEqual(events[-1]["data"]["content"], "模型生成的流式身份回答")
        self.assertEqual(gateway.calls, 1)
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
