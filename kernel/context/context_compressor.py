from __future__ import annotations

from typing import Any

from kernel.token_counter import get_token_counter


class ContextCompressor:
    """Compresses chunks to fit within a token or character budget."""

    def compress(
        self,
        chunks: list[Any],
        max_chars: int = 6000,
        max_tokens: int = 0,
    ) -> str:
        """Compress chunks. Prefers token budget if max_tokens > 0, else char budget."""
        if max_tokens > 0:
            return self._compress_by_tokens(chunks, max_tokens)
        return self._compress_by_chars(chunks, max_chars)

    def _compress_by_tokens(self, chunks: list[Any], max_tokens: int) -> str:
        counter = get_token_counter()
        parts: list[str] = []
        total = 0
        for c in chunks:
            text = str(getattr(c, "content", ""))
            if not text:
                continue
            item = text[:1500]
            item_tokens = counter.count(item)
            if total + item_tokens > max_tokens:
                remain_tokens = max_tokens - total
                if remain_tokens <= 0:
                    break
                # Approximate char budget from remaining tokens
                remain_chars = remain_tokens * 3
                parts.append(item[:remain_chars])
                break
            parts.append(item)
            total += item_tokens
        return "\n\n---\n\n".join(parts)

    def _compress_by_chars(self, chunks: list[Any], max_chars: int) -> str:
        parts: list[str] = []
        total = 0
        for c in chunks:
            text = str(getattr(c, "content", ""))
            if not text:
                continue
            item = text[:1000]
            if total + len(item) > max_chars:
                remain = max_chars - total
                if remain <= 0:
                    break
                parts.append(item[:remain])
                break
            parts.append(item)
            total += len(item)
        return "\n\n---\n\n".join(parts)
