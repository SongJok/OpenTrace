from __future__ import annotations

from typing import Any


class ContextRanker:
    """Heuristic context ranking for P0."""

    def rank(self, chunks: list[Any], top_k: int = 8) -> list[Any]:
        return sorted(chunks, key=lambda c: float(getattr(c, "score", 0.0)), reverse=True)[:top_k]
