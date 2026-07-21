"""
TemporalMemoryIndex — Recency-weighted memory retrieval index.

Applies temporal decay to memory scores so recent events are weighted
higher than older ones.  Integrates with the existing memory layer.
"""

from __future__ import annotations

import time
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)

# Default half-life: events decay to half their weight after 7 days
DEFAULT_HALF_LIFE_SECONDS = 7 * 24 * 3600  # 604800


class TemporalMemoryIndex:
    """Recency-weighted in-memory index for temporal decay scoring.

    Each entry has a timestamp; retrieval applies exponential decay:
      adjusted_score = base_score * 2^(-age_seconds / half_life)
    """

    def __init__(self, half_life_seconds: float = DEFAULT_HALF_LIFE_SECONDS) -> None:
        self._entries: list[dict[str, Any]] = []
        self._half_life = half_life_seconds

    def add(self, content: str, metadata: dict[str, Any] | None = None, score: float = 1.0) -> None:
        self._entries.append({
            "content": content,
            "metadata": metadata or {},
            "base_score": score,
            "timestamp": time.time(),
        })
        logger.debug("TemporalMemory entry added", total_entries=len(self._entries))

    def query(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Return top_k entries with temporal decay applied."""
        now = time.time()
        scored: list[tuple[dict[str, Any], float]] = []

        for entry in self._entries:
            age = now - entry["timestamp"]
            decay = 2.0 ** (-age / self._half_life)
            adjusted = entry["base_score"] * decay
            # Simple keyword overlap bonus
            query_lower = query.lower()
            content_lower = str(entry["content"]).lower()
            overlap = sum(1 for w in query_lower.split() if w in content_lower)
            adjusted += overlap * 0.1
            scored.append((entry, adjusted))

        scored.sort(key=lambda x: -x[1])
        return [
            {
                "content": e["content"],
                "score": round(s, 4),
                "metadata": e["metadata"],
                "age_seconds": now - e["timestamp"],
            }
            for e, s in scored[:top_k]
        ]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
