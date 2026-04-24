from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolSignal:
    name: str
    relevance: float
    success_rate: float = 0.8
    latency_ms: int = 800


class ToolRanker:
    """Heuristic ranking with relevance/success/latency weighting."""

    def __init__(self, w_rel: float = 0.55, w_succ: float = 0.3, w_lat: float = 0.15) -> None:
        self.w_rel = w_rel
        self.w_succ = w_succ
        self.w_lat = w_lat

    def score(self, s: ToolSignal) -> float:
        # latency normalization: faster is better
        lat_score = max(0.0, min(1.0, 1.0 - (s.latency_ms / 5000.0)))
        return self.w_rel * s.relevance + self.w_succ * s.success_rate + self.w_lat * lat_score

    def rank(self, signals: list[ToolSignal], top_k: int = 3) -> list[ToolSignal]:
        return sorted(signals, key=self.score, reverse=True)[:top_k]
