"""TokenCounter — centralized tiktoken-based token counting and smart history truncation.
Replaces the rough heuristic in context_composer.py.
"""

from __future__ import annotations

from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)

_MESSAGE_OVERHEAD_TOKENS = 4


class TokenCounter:
    """Accurate token counting using tiktoken with heuristic fallback."""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoding_name = encoding_name
        self._encoder = None
        self._init_error = None

    @property
    def encoder(self):
        if self._encoder is None and self._init_error is None:
            try:
                import tiktoken

                self._encoder = tiktoken.get_encoding(self._encoding_name)
            except Exception as e:
                self._init_error = str(e)
                logger.debug("tiktoken init failed, using heuristic fallback: %s", e)
        return self._encoder

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self.encoder is not None:
            try:
                return len(self.encoder.encode(text))
            except Exception:
                pass
        return self._heuristic_count(text)

    def count_messages(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            total += _MESSAGE_OVERHEAD_TOKENS
            content = msg.get("content")
            if isinstance(content, str):
                total += self.count(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_text = block.get("text") or str(block)
                        total += self.count(str(block_text))
            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                for tc in tool_calls:
                    total += self.count(
                        str(tc.get("function", {}).get("arguments", ""))
                    )
                    total += self.count(
                        str(tc.get("function", {}).get("name", ""))
                    )
            name = msg.get("name")
            if name and isinstance(name, str):
                total += self.count(name)
            tcid = msg.get("tool_call_id")
            if tcid and isinstance(tcid, str):
                total += self.count(tcid)
        return total

    def truncate_to_budget(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        strategy: str = "keep_system_recent",
        keep_recent_turns: int = 4,
    ) -> list[dict[str, Any]]:
        if strategy == "keep_last":
            return self._truncate_keep_last(messages, max_tokens)
        return self._truncate_keep_system_recent(messages, max_tokens, keep_recent_turns)

    def _truncate_keep_last(
        self, messages: list[dict[str, Any]], max_tokens: int
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        used = 0
        for msg in reversed(messages):
            msg_tokens = _MESSAGE_OVERHEAD_TOKENS + self.count(
                str(msg.get("content", ""))
            )
            if used + msg_tokens > max_tokens and result:
                break
            result.insert(0, msg)
            used += msg_tokens
        return result

    def _truncate_keep_system_recent(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        keep_recent_turns: int = 4,
    ) -> list[dict[str, Any]]:
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        system_tokens = self.count_messages(system_msgs)
        budget = max_tokens - system_tokens
        if budget <= 0:
            return system_msgs

        recent_count = keep_recent_turns * 2
        recent = non_system[-recent_count:] if len(non_system) > recent_count else non_system
        middle = non_system[:-recent_count] if len(non_system) > recent_count else []

        recent_tokens = self.count_messages(recent)
        if recent_tokens >= budget:
            return system_msgs + self._truncate_keep_last(recent, budget)

        remaining = budget - recent_tokens

        kept_middle: list[dict[str, Any]] = []
        for msg in reversed(middle):
            msg_tokens = _MESSAGE_OVERHEAD_TOKENS + self.count(
                str(msg.get("content", ""))
            )
            if msg_tokens > remaining:
                break
            kept_middle.insert(0, msg)
            remaining -= msg_tokens

        pruned_count = len(middle) - len(kept_middle)
        result = list(system_msgs)

        if pruned_count > 0 and kept_middle:
            result.extend(kept_middle)
            placeholder = {
                "role": "system",
                "content": f"[Earlier conversation turns ({pruned_count} messages) omitted to fit token budget.]",
            }
            result.append(placeholder)
        elif pruned_count > 0:
            result.append({
                "role": "system",
                "content": f"[{pruned_count} earlier conversation messages omitted.]",
            })
        else:
            result.extend(kept_middle)

        result.extend(recent)
        return result

    @staticmethod
    def _heuristic_count(text: str) -> int:
        cjk = sum(1 for c in text if "一" <= c <= "鿿" or "㐀" <= c <= "䶿")
        other = len(text) - cjk
        return max(1, int(cjk / 2 + other / 4))


_default_counter: TokenCounter | None = None


def get_token_counter(encoding_name: str = "cl100k_base") -> TokenCounter:
    global _default_counter
    if _default_counter is None:
        _default_counter = TokenCounter(encoding_name=encoding_name)
    return _default_counter


def count_tokens(text: str) -> int:
    return get_token_counter().count(text)


def count_message_tokens(messages: list[dict[str, Any]]) -> int:
    return get_token_counter().count_messages(messages)


def truncate_messages(
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
    strategy: str = "keep_system_recent",
    keep_recent_turns: int | None = None,
) -> list[dict[str, Any]]:
    budget = max_tokens if max_tokens else int(getattr(settings, "context_max_history_tokens", 4096))
    recent = keep_recent_turns if keep_recent_turns else int(getattr(settings, "context_keep_recent_turns_min", 2))
    return get_token_counter().truncate_to_budget(
        messages, max_tokens=budget, strategy=strategy, keep_recent_turns=recent
    )
