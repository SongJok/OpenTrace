from types import SimpleNamespace

import pytest

from infra.config.settings import settings
from model.llm_adapter.base import LLMMessage, LLMResponse
from model.model_gateway.gateway import LLMRole, ModelGateway


def test_provider_quota_errors_are_non_retryable():
    gateway = ModelGateway()
    classification = gateway._classify_exception(
        RuntimeError("403 AllocationQuota.FreeTierOnly: free quota has been exhausted")
    )
    assert classification == "auth"
    assert gateway._retry_policy(RuntimeError("403 forbidden")) == (False, 0.0)


@pytest.mark.asyncio
async def test_null_text_response_is_retried_then_degraded_to_safe_fallback(monkeypatch):
    class NullAdapter:
        config = SimpleNamespace(model="null-model")

        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return LLMResponse(content="null", model="null-model")

    adapter = NullAdapter()
    gateway = ModelGateway()
    monkeypatch.setattr(gateway, "_get_adapter", lambda *args, **kwargs: adapter)
    monkeypatch.setattr(settings, "kernel_all_questions_require_model", False)

    result = await gateway.complete(
        [LLMMessage(role="user", content="你好")],
        role=LLMRole.QUERY,
        fallback_roles=[],
    )

    assert adapter.calls == 3
    assert result.content
    assert result.content.casefold() != "null"
    assert result.model == "offline-fallback"


@pytest.mark.asyncio
async def test_tool_call_without_text_remains_valid(monkeypatch):
    class ToolAdapter:
        config = SimpleNamespace(model="tool-model")

        async def complete(self, *args, **kwargs):
            return LLMResponse(
                content="null",
                model="tool-model",
                tool_calls=[{"name": "emit_intent_plan", "arguments": "{}"}],
            )

    gateway = ModelGateway()
    monkeypatch.setattr(gateway, "_get_adapter", lambda *args, **kwargs: ToolAdapter())

    result = await gateway.complete(
        [LLMMessage(role="user", content="规划")],
        role=LLMRole.PLANNING,
        fallback_roles=[],
    )

    assert result.tool_calls
