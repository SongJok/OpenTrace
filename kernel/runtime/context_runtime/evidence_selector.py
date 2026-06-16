"""
证据选择器 — 从先前轮次中选择和排序证据用于上下文注入。

当当前查询引用或依赖于早期轮次的证据时，
此选择器检索并排序该证据以包含在提示词中。
"""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class EvidenceSelector:
    """为当前查询选择相关的先前轮次证据。

    封装 EvidenceBus 从早期轮次检索证据，按与当前查询的
    相关性评分，并格式化以插入提示词。
    """

    def __init__(self, evidence_bus: Any = None) -> None:
        self._evidence_bus = evidence_bus

    async def _ensure_bus(self) -> Any:
        if self._evidence_bus is None:
            from kernel.runtime.evidence_bus import evidence_bus
            self._evidence_bus = evidence_bus
        return self._evidence_bus

    async def select(
        self,
        query: str,
        max_evidence: int = 5,
        min_credibility: float = 0.4,
    ) -> list[dict[str, Any]]:
        """为当前查询选择相关证据。

        返回包含内容、来源和可信度的证据字典列表，
        按与查询的相关性排序。
        """
        bus = await self._ensure_bus()
        if bus is None:
            return []

        try:
            all_evidence = await bus.collect()
        except Exception as exc:
            logger.debug("EvidenceSelector collect failed", error=str(exc))
            return []

        if not all_evidence:
            return []

        # 按可信度过滤
        credible = [
            e for e in all_evidence
            if getattr(e, "credibility_score", 0) >= min_credibility
        ]
        if not credible:
            return []

        # 按与查询的相关性评分
        query_tokens = set(self._tokenize(query))
        scored: list[tuple[Any, float]] = []
        for ev in credible:
            content = getattr(ev, "content", "")
            content_tokens = self._tokenize(content)
            if not content_tokens:
                score = 0.0
            else:
                overlap = sum(1 for t in query_tokens if t in content_tokens)
                score = overlap / max(len(query_tokens), 1)
                # 按可信度加权
                score *= getattr(ev, "credibility_score", 0.5)
            scored.append((ev, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        result: list[dict[str, Any]] = []
        for ev, score in scored[:max_evidence]:
            if score <= 0:
                continue
            provenance = getattr(ev, "provenance", None)
            result.append({
                "content": getattr(ev, "content", "")[:500],
                "source": getattr(provenance, "source", "unknown") if provenance else "unknown",
                "credibility": getattr(ev, "credibility_score", 0.5),
                "relevance": round(score, 3),
            })

        return result

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        import re

        lowered = text.lower()
        tokens: list[str] = []
        tokens.extend(re.findall(r'[a-z]{2,}', lowered))
        tokens.extend(re.findall(r'[一-鿿]+', lowered))
        tokens.extend(re.findall(r'\d+', lowered))
        return tokens
