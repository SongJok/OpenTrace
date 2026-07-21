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


def test_memory_learner_proactively_extracts_stable_profile_and_preference():
    candidates = MemoryLearner._extract_proactive(
        "我叫林舟。\n我偏好使用简洁的中文回答。"
    )

    assert [(item["key"], item["kind"]) for item in candidates] == [
        ("profile.name", "profile"),
        ("preference.response_style", "preference"),
    ]
    assert all(item["explicit"] is False for item in candidates)
    assert all(item["confidence"] >= 0.85 for item in candidates)


def test_memory_learner_proactively_extracts_goals_workflows_and_project_facts():
    candidates = MemoryLearner._extract_proactive(
        "我的长期目标是成为可靠的架构师。\n"
        "我的工作流程是先写测试，再实现功能。\n"
        "本项目数据库使用 PostgreSQL。"
    )

    assert {item["kind"] for item in candidates} == {"fact", "workflow"}
    assert any(item["key"].startswith("goal.long_term.") for item in candidates)
    assert any(item["key"].startswith("workflow.routine.") for item in candidates)
    project = next(item for item in candidates if item["key"].startswith("project.fact."))
    assert project["scope_type"] == "project"


def test_memory_learner_rejects_transient_questions_and_sensitive_profile_data():
    assert MemoryLearner._extract_proactive("今天请用表格回答当前问题。") == []
    assert MemoryLearner._extract_proactive("我的银行卡号是 6222021234567890。") == []
    assert MemoryLearner._extract_explicit("请记住：我的手机号是 13800138000。") == []


def test_memory_learner_uses_proactive_fallback_when_model_output_is_invalid(monkeypatch):
    class InvalidGateway:
        async def complete(self, *args, **kwargs):
            return SimpleNamespace(content="not-json")

    monkeypatch.setattr(
        "kernel.agent_loop.memory_learner.get_model_gateway", lambda: InvalidGateway()
    )

    candidates = asyncio.run(MemoryLearner()._extract("我的代号是主动-42。"))

    assert candidates[0]["content"] == "我的代号是主动-42"
    assert candidates[0]["explicit"] is False
    assert candidates[0]["confidence"] >= 0.85


def test_only_governed_proactive_candidates_auto_activate():
    assert MemoryLearner._candidate_status(
        confidence=0.90,
        explicit=False,
        learning_mode="proactive",
    ) == "active"
    assert MemoryLearner._candidate_status(
        confidence=0.99,
        explicit=False,
        learning_mode="model",
    ) == "pending"
    assert MemoryLearner._candidate_status(
        confidence=1.0,
        explicit=True,
        learning_mode="explicit",
    ) == "active"


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
