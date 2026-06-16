"""
证据排序器 — 多维度证据排序。

按以下维度对证据评分：可信度、相关性（与查询）、新鲜度（时效性）、
来源权威性和内容质量。生成可供融合使用的排序证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RankedEvidence:
    """带有排序评分的证据。"""
    evidence_id: str = ""
    content: str = ""
    source: str = ""
    credibility_score: float = 0.5
    relevance_score: float = 0.5
    freshness_score: float = 0.5
    authority_score: float = 0.5
    composite_score: float = 0.5
    rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class EvidenceRanker:
    """多维度证据排序。

    权重（可配置）：
    - 可信度：0.35（来源 + 内容的可信程度）
    - 相关性：0.35（与查询的相关程度）
    - 新鲜度：0.15（时效性）
    - 权威性：0.15（来源权威性）
    """

    def __init__(
        self,
        w_credibility: float = 0.35,
        w_relevance: float = 0.35,
        w_freshness: float = 0.15,
        w_authority: float = 0.15,
    ) -> None:
        self.w_cred = w_credibility
        self.w_rel = w_relevance
        self.w_fresh = w_freshness
        self.w_auth = w_authority

    def rank(
        self,
        query: str,
        evidence_list: list[Any],
        top_k: int = 10,
    ) -> list[RankedEvidence]:
        """按综合评分对证据排序。

        Args:
            query: 用于相关性评分的用户查询。
            evidence_list: Evidence 对象列表。
            top_k: 返回的最大数量。

        Returns:
            按 composite_score 降序排列的 RankedEvidence 列表。
        """
        if not evidence_list:
            return []

        query_tokens = set(self._tokenize(query))

        ranked: list[RankedEvidence] = []
        for ev in evidence_list:
            content = getattr(ev, "content", "")
            credibility = getattr(ev, "credibility_score", 0.5)
            provenance = getattr(ev, "provenance", None)
            source = getattr(provenance, "source", "unknown") if provenance else "unknown"
            timestamp = getattr(provenance, "timestamp", None) if provenance else None

            relevance = self._compute_relevance(query_tokens, content)
            freshness = self._compute_freshness(timestamp)
            authority = self._compute_authority(source)

            composite = (
                self.w_cred * credibility
                + self.w_rel * relevance
                + self.w_fresh * freshness
                + self.w_auth * authority
            )

            ranked.append(RankedEvidence(
                evidence_id=getattr(ev, "evidence_id", ""),
                content=content,
                source=source,
                credibility_score=credibility,
                relevance_score=round(relevance, 3),
                freshness_score=round(freshness, 3),
                authority_score=round(authority, 3),
                composite_score=round(composite, 3),
            ))

        ranked.sort(key=lambda r: r.composite_score, reverse=True)

        for i, r in enumerate(ranked[:top_k]):
            r.rank = i + 1

        return ranked[:top_k]

    # ── 评分辅助方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _compute_relevance(query_tokens: set[str], content: str) -> float:
        if not query_tokens or not content:
            return 0.5
        content_lower = content.lower()
        hits = sum(1 for t in query_tokens if t.lower() in content_lower)
        # 标题加分：出现在前部的 token 更相关
        early = content[:200].lower()
        early_hits = sum(1 for t in query_tokens if t.lower() in early)
        score = (hits + early_hits * 1.5) / (len(query_tokens) * 2.5)
        return min(score, 1.0)

    @staticmethod
    def _compute_freshness(timestamp: datetime | None) -> float:
        if timestamp is None:
            return 0.5
        now = datetime.now(timezone.utc)
        age_hours = (now - timestamp).total_seconds() / 3600
        # 24 小时半衰期
        return max(0.1, 1.0 / (1.0 + age_hours / 24.0))

    @staticmethod
    def _compute_authority(source: str) -> float:
        """来源权威性评分。"""
        authority_map: dict[str, float] = {
            "data": 0.9,
            "rag": 0.7,
            "skills": 0.8,
            "web": 0.5,
            "tool": 0.7,
            "rule_engine": 0.8,
            "vision": 0.6,
        }
        return authority_map.get(source.lower(), 0.5)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        import re
        lowered = text.lower()
        tokens: list[str] = []
        tokens.extend(re.findall(r'[a-z]+\d+[a-z]*|\d+[a-z]+', lowered))  # 字母数字
        tokens.extend(re.findall(r'[a-z]{2,}', lowered))
        tokens.extend(re.findall(r'[一-鿿]+', lowered))
        tokens.extend(re.findall(r'\d+', lowered))
        return tokens
