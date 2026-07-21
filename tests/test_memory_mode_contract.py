"""Temporary conversations must never consume personalization memory."""

import asyncio
from types import SimpleNamespace

from gateway.api_gateway.routers.responses import ResponseCreateRequest
from kernel.turn_enrichment import apply_preference_and_memory, personalization_memory_enabled


def test_memory_mode_defaults_to_enabled_for_responses_clients() -> None:
    assert ResponseCreateRequest(input="hello").memory_mode == "enabled"


def test_temporary_memory_mode_skips_personalization_reads() -> None:
    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        query="hello",
        conversation_state=None,
        metadata={
            "memory_mode": "temporary",
            "user_preferences": ["must not be used"],
            "user_preference_context_block": "must not be used",
        },
    )

    result = asyncio.run(apply_preference_and_memory(request))

    assert not personalization_memory_enabled(request.metadata)
    assert result.memory_context == []
    assert result.metadata["memory_status"] == "disabled"
    assert "user_preferences" not in result.metadata
    assert "user_preference_context_block" not in result.metadata
