"""Contracts for the single production Agent Loop."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from infra.config.settings import settings
from kernel.agent_loop.context import ContextAssembler
from kernel.agent_loop.contracts import ExecutionProfile, SideEffect, parse_tool_specs
from kernel.agent_loop.memory_learner import MemoryLearner
from kernel.agent_loop.runner import AgentLoop


def test_tool_schema_is_strict_and_namespaced_policy_is_not_sent_to_provider():
    spec = parse_tool_specs([{
        "type": "function",
        "name": "save_note",
        "description": "Save a note",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        "opentrace": {"side_effect": "write", "required_permissions": ["notes:write"]},
    }])[0]
    provider = spec.as_openai_tool()
    assert spec.side_effect == SideEffect.WRITE
    assert provider["strict"] is True
    assert provider["parameters"]["additionalProperties"] is False
    assert provider["parameters"]["required"] == ["text"]
    assert "opentrace" not in provider


def test_model_profiles_are_configurable_and_include_reasoning_summaries():
    fast, fast_reasoning = AgentLoop._model_profile(ExecutionProfile.FAST, {})
    deep, deep_reasoning = AgentLoop._model_profile(ExecutionProfile.DEEP, {})
    assert fast == settings.default_llm_fast_openai_model
    assert deep == settings.default_llm_deep_openai_model
    assert fast_reasoning == {"effort": "low", "summary": "auto"}
    assert deep_reasoning == {"effort": "high", "summary": "detailed"}


def test_memory_learner_rejects_secrets_before_model_extraction():
    assert MemoryLearner._contains_secret("api_key = sk-secret-value-123456789")
    assert MemoryLearner._contains_secret("密码：hunter2")
    assert not MemoryLearner._contains_secret("我喜欢简洁的中文回答")


def test_memory_learner_has_deterministic_fallback_for_explicit_memory():
    candidates = MemoryLearner._extract_explicit(
        "请记住：我的跨会话测试代号是星河-7391。以后问到时直接回答。"
    )

    assert len(candidates) == 1
    assert candidates[0]["content"] == "我的跨会话测试代号是星河-7391"
    assert candidates[0]["explicit"] is True
    assert candidates[0]["scope_type"] == "user"
    assert candidates[0]["key"].startswith("explicit.fact.")


def test_memory_learner_classifies_explicit_preferences():
    candidate = MemoryLearner._extract_explicit(
        "Please remember that I prefer concise Chinese answers."
    )[0]

    assert candidate["kind"] == "preference"
    assert candidate["confidence"] == 1.0


def test_memory_learner_uses_explicit_fallback_when_model_output_is_invalid(monkeypatch):
    class InvalidGateway:
        async def complete(self, *args, **kwargs):
            return SimpleNamespace(content="offline fallback is not JSON")

    monkeypatch.setattr(
        "kernel.agent_loop.memory_learner.get_model_gateway", lambda: InvalidGateway()
    )

    candidates = asyncio.run(MemoryLearner()._extract("请记住：我的代号是北辰-42。"))

    assert candidates[0]["content"] == "我的代号是北辰-42"
    assert candidates[0]["explicit"] is True


def test_explicit_memory_uses_stable_key_even_when_model_returns_an_explicit_candidate(
    monkeypatch,
):
    class ModelGateway:
        async def complete(self, *args, **kwargs):
            return SimpleNamespace(
                content=(
                    '[{"content":"模型值","key":"unstable_model_key","kind":"fact",'
                    '"confidence":1,"salience":1,"explicit":true,"sensitive":false}]'
                )
            )

    monkeypatch.setattr(
        "kernel.agent_loop.memory_learner.get_model_gateway", lambda: ModelGateway()
    )

    candidates = asyncio.run(MemoryLearner()._extract("请记住：我的代号是北辰-42。"))

    assert len(candidates) == 1
    assert candidates[0]["content"] == "我的代号是北辰-42"
    assert candidates[0]["key"].startswith("explicit.fact.")


def test_memory_ranker_excludes_irrelevant_user_facts_but_keeps_preferences():
    now = datetime.now(UTC)
    memories = [
        SimpleNamespace(
            id="irrelevant",
            content="验证管理员",
            pinned=False,
            kind="fact",
            scope_type="user",
            salience=1.0,
            confidence=1.0,
            updated_at=now,
        ),
        SimpleNamespace(
            id="relevant",
            content="我的跨会话测试代号是星河-7391",
            pinned=False,
            kind="fact",
            scope_type="user",
            salience=0.5,
            confidence=1.0,
            updated_at=now,
        ),
        SimpleNamespace(
            id="preference",
            content="我偏好简洁中文回答",
            pinned=False,
            kind="preference",
            scope_type="user",
            salience=0.5,
            confidence=1.0,
            updated_at=now,
        ),
    ]

    ranked = ContextAssembler._rank_memories(memories, "我的测试代号是什么")

    assert {item.id for item in ranked} == {"relevant", "preference"}
