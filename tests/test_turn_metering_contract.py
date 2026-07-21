"""LLM turn token metering."""

from __future__ import annotations

from infra.observability.turn_metering import (
    add_llm_usage,
    get_turn_tokens,
    merge_turn_tokens_into_metadata,
    reset_turn_tokens,
)


def test_turn_metering_accumulates():
    reset_turn_tokens()
    add_llm_usage(prompt_tokens=100, completion_tokens=50)
    add_llm_usage(prompt_tokens=20, completion_tokens=10)
    tok = get_turn_tokens()
    assert tok["prompt_tokens"] == 120
    assert tok["completion_tokens"] == 60
    md = merge_turn_tokens_into_metadata({})
    assert md["prompt_tokens"] == 120