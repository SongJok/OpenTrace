from __future__ import annotations

from typing import Any


class ContextCompressor:
    """Token-budget style compressor (character-budget in P0)."""

    def compress(self, chunks: list[Any], max_chars: int = 6000) -> str:
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
