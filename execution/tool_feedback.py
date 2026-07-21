from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolFeedbackEvent:
    tool_name: str
    success: bool
    latency_ms: int


class ToolFeedbackStore:
    """In-memory feedback store for P1 baseline."""

    def __init__(self) -> None:
        self._stats: dict[str, dict[str, float]] = {}

    def record(self, ev: ToolFeedbackEvent) -> None:
        row = self._stats.setdefault(ev.tool_name, {"count": 0, "success": 0, "lat_total": 0.0})
        row["count"] += 1
        row["success"] += 1 if ev.success else 0
        row["lat_total"] += float(ev.latency_ms)

    def snapshot(self, tool_name: str) -> tuple[float, int]:
        row = self._stats.get(tool_name)
        if not row or row["count"] <= 0:
            return 0.8, 800
        success_rate = float(row["success"] / row["count"])
        avg_lat = int(row["lat_total"] / row["count"])
        return success_rate, avg_lat


tool_feedback_store = ToolFeedbackStore()
