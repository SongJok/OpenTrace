"""Contract tests for explicit custom instructions and their precedence."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gateway.api_gateway.routers.personalization import CustomInstructionPayload
from infra.storage.models import UserCustomInstruction
from kernel.preference_injection import apply_preference_injection_for_turn
from kernel.runtime.context import RuntimeContext
from kernel.turn_enrichment import apply_preference_and_memory


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Db:
    def __init__(self, value):
        self.value = value

    async def execute(self, _statement):
        return _Result(self.value)


def test_custom_instruction_payload_is_bounded_and_defaults_enabled() -> None:
    payload = CustomInstructionPayload(about_user="me", response_style="concise")
    assert payload.enabled is True
    assert any(
        getattr(item, "max_length", None) == 4000
        for item in CustomInstructionPayload.model_fields["about_user"].metadata
    )
    with pytest.raises(ValidationError):
        CustomInstructionPayload(about_user="x" * 4001)


def test_custom_instruction_model_has_scoped_unique_key() -> None:
    names = {
        tuple(constraint.columns.keys())
        for constraint in UserCustomInstruction.__table__.constraints
        if getattr(constraint, "columns", None)
    }
    assert ("user_id", "tenant_id", "workspace_id") in names


def test_runtime_context_exposes_custom_instruction_metadata() -> None:
    ctx = RuntimeContext(
        request_id="r1",
        session_id="s1",
        user_id="u1",
        query="hello",
        custom_instruction_block="回答简洁",
    )
    assert ctx.to_metadata_dict()["custom_instruction_block"] == "回答简洁"


def test_context_assembler_loads_custom_instructions_in_tenant_scope() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "kernel/agent_loop/context.py").read_text()
    assert "UserCustomInstruction.tenant_id == response.tenant_id" in text
    assert "UserCustomInstruction.workspace_id == response.workspace_id" in text
    assert "用户提供的背景" in text
    assert "用户偏好的回答方式" in text


def test_custom_instructions_survive_temporary_memory_mode() -> None:
    request = SimpleNamespace(
        session_id="s1",
        user_id="u1",
        query="hello",
        conversation_state=None,
        metadata={"memory_mode": "temporary", "custom_instruction_block": "回答简洁"},
    )
    result = asyncio.run(apply_preference_and_memory(request))
    assert "用户明确指令" in result.metadata["user_preference_context_block"]
    assert result.memory_context == []


def test_custom_instructions_precede_learned_preferences(monkeypatch) -> None:
    async def _empty(_user_id: str, _session_id: str):
        return []

    monkeypatch.setattr("kernel.preference_injection._load_user_memory_preferences", _empty)
    out = asyncio.run(
        apply_preference_injection_for_turn(
            user_id="u1",
            session_id="s1",
            metadata={"custom_instruction_block": "回答简洁"},
        )
    )
    assert out["user_preference_context_block"].startswith("## 用户明确指令")
