"""Memory compression / archive hints — prevent memory explosion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompressionPlan:
    summarize: bool = False
    cluster: bool = False
    archive_ids: list[str] = field(default_factory=list)
    forget_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "summarize": self.summarize,
            "cluster": self.cluster,
            "archive_ids": list(self.archive_ids),
            "forget_ids": list(self.forget_ids),
            "reason": self.reason,
        }


def plan_memory_maintenance(
    memories: list[dict[str, Any]],
    *,
    max_active: int = 128,
    archive_confidence_below: float = 0.25,
) -> CompressionPlan:
    if len(memories) <= max_active:
        return CompressionPlan(reason="within_budget")
    plan = CompressionPlan(summarize=True, cluster=True, reason="memory_budget_exceeded")
    sorted_mem = sorted(
        memories,
        key=lambda m: float(m.get("confidence", m.get("credibility_score", 0.5)) or 0.5),
    )
    overflow = len(memories) - max_active
    for m in sorted_mem[:overflow]:
        mid = str(m.get("id", m.get("memory_id", "")))
        conf = float(m.get("confidence", m.get("credibility_score", 0.5)) or 0.5)
        if not mid:
            continue
        if conf < archive_confidence_below:
            plan.forget_ids.append(mid)
        else:
            plan.archive_ids.append(mid)
    return plan