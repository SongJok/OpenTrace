"""Contracts for the single production Agent Loop."""

from infra.config.settings import settings
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
