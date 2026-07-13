"""Normal chat turns may not complete from rules, caches or raw tool output."""

import asyncio

from infra.config.settings import settings
from kernel.cognitive_kernel import CognitiveKernel, KernelRequest, KernelResponse


class _Gateway:
    def __init__(self) -> None:
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return KernelResponse(
            content="由主模型生成的回答",
            session_id=request.session_id,
            route="cognitive_runtime_v2",
            model="primary-query-model",
            metadata={"model_call_count": 1, "model_call_id": "mc_test"},
        )

    async def stream(self, request):
        self.requests.append(request)
        yield {
            "type": "final_answer",
            "data": {
                "content": "由主模型生成的流式回答",
                "route": "cognitive_runtime_v2",
                "metadata": {"model_call_count": 1, "model_call_id": "mc_stream"},
            },
        }


def test_v5_facade_never_returns_direct_answer_when_model_is_required(monkeypatch) -> None:
    from kernel.routing.v5_facade import get_v5_routing_facade

    monkeypatch.setattr(settings, "kernel_all_questions_require_model", True)
    result = asyncio.run(
        get_v5_routing_facade(CognitiveKernel()).try_fast_path(
            KernelRequest(query="你是谁"),
            session_id="s1",
            is_multi=False,
            context_hash_fn=lambda _history: "",
            t0=0.0,
        )
    )
    assert result is None


def test_capability_help_uses_runtime_when_model_is_required(monkeypatch) -> None:
    gateway = _Gateway()
    monkeypatch.setattr(settings, "kernel_all_questions_require_model", True)
    monkeypatch.setattr("kernel.runtime_gateway.get_runtime_gateway", lambda: gateway)

    response = asyncio.run(
        CognitiveKernel().run(
            KernelRequest(
                query="你可以做什么",
                session_id="s1",
                user_id="u1",
                metadata={"memory_mode": "temporary"},
            )
        )
    )

    assert response.content == "由主模型生成的回答"
    assert response.route == "cognitive_runtime_v2"
    assert len(gateway.requests) == 1
    assert gateway.requests[0].metadata["model_required"] is True


def test_streaming_identity_cache_cannot_bypass_primary_model(monkeypatch) -> None:
    from memory.working_memory.working_memory import cache_identity_answer, clear_session_memory

    gateway = _Gateway()
    monkeypatch.setattr(settings, "kernel_all_questions_require_model", True)
    monkeypatch.setattr("kernel.runtime_gateway.get_runtime_gateway", lambda: gateway)
    cache_identity_answer("model-required", "你是谁", "旧缓存答案")

    async def _collect():
        return [
            event
            async for event in CognitiveKernel().stream(
                KernelRequest(
                    query="你是谁",
                    session_id="model-required",
                    metadata={"memory_mode": "temporary"},
                )
            )
        ]

    try:
        events = asyncio.run(_collect())
    finally:
        clear_session_memory("model-required")

    assert events[-1]["data"]["content"] == "由主模型生成的流式回答"
    assert len(gateway.requests) == 1
