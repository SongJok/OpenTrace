"""Small, transport-neutral text streaming helper.

The core turn processor uses this helper to turn already-generated text into a
predictable sequence of public events. It intentionally emits only displayable
text and completion information; it is not a channel for model reasoning.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass(frozen=True)
class StreamEvent:
    """A transport-neutral event that can be serialized as SSE or WebSocket."""

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)


class StreamingEngine:
    """Chunk display text without splitting fenced code blocks mid-fence."""

    DEFAULT_CONFIG = {
        "chunk_size": 24,
        "chunk_delay_ms": 0,
        "sentence_delay_ms": 0,
        "code_block_delay_ms": 0,
    }

    def __init__(self, **config: int) -> None:
        self.config = {**self.DEFAULT_CONFIG, **config}

    async def stream_text(self, text: str) -> AsyncIterator[StreamEvent]:
        """Yield text chunks followed by exactly one terminal ``done`` event."""
        position = 0
        previous = ""
        text = text or ""
        while position < len(text):
            if text.startswith("```", position):
                chunk, next_position = self._extract_code_block(text, position)
            else:
                next_position = min(position + int(self.config["chunk_size"]), len(text))
                chunk = text[position:next_position]
                boundary = max(chunk.rfind(ch) for ch in ("\n", "。", "！", "？", ".", "!", "?"))
                if boundary >= 0 and boundary + 1 < len(chunk):
                    chunk = chunk[: boundary + 1]
                    next_position = position + len(chunk)

            if chunk:
                yield StreamEvent("content", {"text": chunk})
                delay_ms = self._calculate_delay(chunk, previous, next_position)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000)
                previous = chunk
            position = next_position

        yield StreamEvent("done", {"complete": True})

    def _extract_code_block(self, text: str, start: int) -> tuple[str, int]:
        """Return a complete fenced block, or the remaining text if unclosed."""
        closing = text.find("```", start + 3)
        if closing < 0:
            return text[start:], len(text)
        end = closing + 3
        return text[start:end], end

    def _calculate_delay(self, chunk: str, previous: str, position: int) -> int:
        """Choose the public pacing hint for a display chunk."""
        del previous, position
        if chunk.lstrip().startswith("```"):
            return int(self.config["code_block_delay_ms"])
        if chunk.rstrip().endswith(("。", "！", "？", ".", "!", "?")):
            return int(self.config["sentence_delay_ms"])
        return int(self.config["chunk_delay_ms"])
