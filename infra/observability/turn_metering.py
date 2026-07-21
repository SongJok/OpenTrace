"""Per-turn LLM token accumulation (request context)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_turn_tokens: ContextVar[dict[str, int]] = ContextVar(
    "turn_llm_tokens", default={"prompt_tokens": 0, "completion_tokens": 0}
)


def reset_turn_tokens() -> None:
    _turn_tokens.set({"prompt_tokens": 0, "completion_tokens": 0})


def add_llm_usage(*, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    cur = dict(_turn_tokens.get())
    cur["prompt_tokens"] = int(cur.get("prompt_tokens", 0)) + int(prompt_tokens or 0)
    cur["completion_tokens"] = int(cur.get("completion_tokens", 0)) + int(completion_tokens or 0)
    _turn_tokens.set(cur)


def get_turn_tokens() -> dict[str, int]:
    return dict(_turn_tokens.get())


def merge_turn_tokens_into_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    md = dict(metadata or {})
    tok = get_turn_tokens()
    if tok.get("prompt_tokens") or tok.get("completion_tokens"):
        md["prompt_tokens"] = tok.get("prompt_tokens", 0)
        md["completion_tokens"] = tok.get("completion_tokens", 0)
    return md