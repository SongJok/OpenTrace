"""StrategyMemory — 记忆各类查询适用的执行策略。

跟踪 (capabilities_used, domain, strategy_type) → 成功率，
供 StrategyBuilder 做自适应执行决策，减少硬编码启发式。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from kernel.capability_intelligence.profile import StrategyRecord
from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class StrategyStats:
    strategy_type: str = ""
    capabilities_used: tuple[str, ...] = field(default_factory=tuple)
    query_domain: str = ""
    total_attempts: int = 0
    success_rate: float = 0.0
    avg_latency_ms: int = 0
    last_used: float = 0.0
    last_success: bool = False


@dataclass
class StrategyRecommendation:
    strategy_type: str = "direct"
    confidence: float = 0.0
    reasoning: str = ""
    alternatives: list[tuple[str, float]] = field(default_factory=list)


class StrategyMemory:
    """记忆哪些执行策略适用于哪些查询类型与能力组合。

    模块级单例：`strategy_memory = StrategyMemory()`
    """

    def __init__(self, max_records: int = 300) -> None:
        self._records: deque[StrategyRecord] = deque(maxlen=max_records)
        # 复合键：(strategy_type, frozenset_str, domain) -> [(success, latency)]
        self._index: dict[tuple[str, str, str], list[tuple[bool, int]]] = {}

    def record(self, record: StrategyRecord) -> None:
        """存储策略执行记录并更新索引。"""
        self._records.append(record)

        caps_key = ",".join(sorted(record.capabilities_used)) if record.capabilities_used else "none"
        key = (record.strategy_type, caps_key, record.query_domain)
        self._index.setdefault(key, []).append((record.success, record.latency_ms))
        if len(self._index[key]) > 100:
            self._index[key] = self._index[key][-100:]

    def recommend(
        self, capabilities: list[str], query_domain: str = "general"
    ) -> StrategyRecommendation:
        """为能力集合与领域推荐最佳执行策略。

        匹配优先级：
        1. 精确匹配：相同能力 + 相同领域
        2. 部分匹配：相同策略 + 能力重叠
        3. 跨领域匹配：相同策略，任意领域
        4. 回退：以 "sequential" 作为安全默认策略
        """
        caps_key = ",".join(sorted(capabilities)) if capabilities else "none"
        cap_set = set(capabilities)

        # 1. 精确匹配
        exact = self._query_index(caps_key, query_domain)
        if exact:
            return exact

        # 2. 部分匹配：相同策略 + 能力重叠 + 相同领域
        partial_matches: list[tuple[str, float, int, str]] = []
        for (strat, ck, domain), outcomes in self._index.items():
            if domain != query_domain and domain != "general":
                continue
            indexed_caps = set(ck.split(",")) if ck != "none" else set()
            overlap = len(cap_set & indexed_caps)
            if overlap > 0:
                successes = sum(1 for s, _ in outcomes if s)
                rate = successes / len(outcomes)
                score = rate * overlap / len(cap_set)
                if score > 0:
                    partial_matches.append((strat, score, len(outcomes), ck))

        if partial_matches:
            partial_matches.sort(key=lambda x: (x[1], x[2]), reverse=True)
            best = partial_matches[0]
            alternatives = [(s, round(sc, 4)) for s, sc, _, _ in partial_matches[1:4]]
            return StrategyRecommendation(
                strategy_type=best[0],
                confidence=round(best[1], 4),
                reasoning=f"部分匹配（能力重叠，{best[2]}次采样）",
                alternatives=alternatives,
            )

        # 3. 跨领域匹配：相同策略，任意领域
        agnostic: dict[str, tuple[float, int]] = {}
        for (strat, ck, _), outcomes in self._index.items():
            indexed_caps = set(ck.split(",")) if ck != "none" else set()
            overlap = len(cap_set & indexed_caps)
            if overlap > 0:
                successes = sum(1 for s, _ in outcomes if s)
                rate = successes / len(outcomes)
                score = rate * overlap / len(cap_set)
                if score > agnostic.get(strat, (0, 0))[0]:
                    agnostic[strat] = (score, len(outcomes))

        if agnostic:
            best_strat = max(agnostic, key=lambda s: agnostic[s])
            score, count = agnostic[best_strat]
            alts = sorted(
                [(s, round(sc, 4)) for s, (sc, _) in agnostic.items() if s != best_strat],
                key=lambda x: x[1], reverse=True
            )[:3]
            return StrategyRecommendation(
                strategy_type=best_strat,
                confidence=round(score, 4),
                reasoning=f"跨领域匹配（{count}次采样）",
                alternatives=alts,
            )

        # 4. 回退
        return StrategyRecommendation(
            strategy_type="sequential",
            confidence=0.1,
            reasoning="无历史数据，使用安全默认策略",
            alternatives=[("parallel", 0.05), ("direct", 0.05)],
        )

    def _query_index(self, caps_key: str, domain: str) -> StrategyRecommendation | None:
        """尝试精确匹配能力+领域，然后尝试能力+'general'。"""
        for dm in (domain, "general"):
            best: tuple[str, float, int] | None = None
            alternatives: list[tuple[str, float]] = []
            for strat in ("direct", "parallel", "sequential", "compare"):
                key = (strat, caps_key, dm)
                outcomes = self._index.get(key, [])
                if not outcomes:
                    continue
                successes = sum(1 for s, _ in outcomes if s)
                rate = successes / len(outcomes)
                if best is None or rate > best[1]:
                    if best is not None:
                        alternatives.append((best[0], round(best[1], 4)))
                    best = (strat, rate, len(outcomes))
                else:
                    alternatives.append((strat, round(rate, 4)))

            if best:
                return StrategyRecommendation(
                    strategy_type=best[0],
                    confidence=round(best[1], 4),
                    reasoning=f"精确匹配（domain={dm}，{best[2]}次采样）",
                    alternatives=alternatives[:3],
                )

        return None

    def get_best_strategy_for_domain(self, domain: str) -> str:
        """给定领域的整体最佳策略。"""
        domain_stats: dict[str, list[float]] = {}
        for (strat, _, dm), outcomes in self._index.items():
            if dm == domain:
                successes = sum(1 for s, _ in outcomes if s)
                rate = successes / len(outcomes)
                domain_stats.setdefault(strat, []).append(rate)

        if not domain_stats:
            return "sequential"

        avg_rates = {
            strat: sum(rates) / len(rates)
            for strat, rates in domain_stats.items()
        }
        return max(avg_rates, key=lambda s: avg_rates[s])

    def get_stats(
        self, strategy_type: str | None = None, domain: str | None = None
    ) -> list[StrategyStats]:
        """列出策略统计，可按条件过滤。"""
        aggregated: dict[tuple[str, str, str], list[tuple[bool, int, float]]] = {}
        for (strat, ck, dm), outcomes in self._index.items():
            if strategy_type and strat != strategy_type:
                continue
            if domain and dm != domain:
                continue
            for s, lat in outcomes:
                aggregated.setdefault((strat, ck, dm), []).append((s, lat, 0.0))

        results: list[StrategyStats] = []
        for (strat, ck, dm), data in aggregated.items():
            total = len(data)
            successes = sum(1 for s, _, _ in data if s)
            avg_lat = sum(lat for _, lat, _ in data) // total
            results.append(StrategyStats(
                strategy_type=strat,
                capabilities_used=tuple(ck.split(",")) if ck != "none" else (),
                query_domain=dm,
                total_attempts=total,
                success_rate=round(successes / total, 4),
                avg_latency_ms=avg_lat,
            ))

        return sorted(results, key=lambda s: s.success_rate, reverse=True)

    @property
    def total_records(self) -> int:
        return len(self._records)


# 模块级单例
strategy_memory = StrategyMemory()
