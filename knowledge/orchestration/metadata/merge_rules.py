"""知识冲突检测规则；冲突内容始终进入人工审核。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

AUTHORITY_RANK = {
    "official": 7,
    "approved": 6,
    "verified": 5,
    "contextual": 4,
    "inferred": 3,
    "user_memory": 2,
    "external": 1,
    "unknown": 0,
}


@dataclass(frozen=True, slots=True)
class MergeDecision:
    action: str
    preferred_id: str | None
    candidate_ids: tuple[str, ...]
    reason: str
    requires_human_review: bool


class MergeRules:
    """对重复或冲突候选给出可解释决策，不静默覆盖知识。"""

    def decide(self, candidates: list[dict[str, Any]]) -> MergeDecision:
        if not candidates:
            return MergeDecision("skip", None, (), "no_candidates", False)
        ids = tuple(str(item.get("id") or "") for item in candidates)
        normalized = {
            " ".join(str(item.get("text") or item.get("content") or "").lower().split())
            for item in candidates
        }
        if len(normalized) > 1:
            return MergeDecision(
                "review",
                None,
                ids,
                "conflicting_content_requires_human_review",
                True,
            )
        preferred = max(candidates, key=self._priority)
        return MergeDecision(
            "deduplicate",
            str(preferred.get("id") or ""),
            ids,
            "same_content_keep_highest_authority_and_newest",
            False,
        )

    @staticmethod
    def _priority(item: dict[str, Any]) -> tuple[int, float, str]:
        authority = AUTHORITY_RANK.get(str(item.get("authority") or "unknown").lower(), 0)
        confidence = float(item.get("confidence", 0.0) or 0.0)
        updated = item.get("updated_at") or ""
        if isinstance(updated, datetime):
            updated = updated.isoformat()
        return authority, confidence, str(updated)
