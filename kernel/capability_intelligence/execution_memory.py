"""ExecutionMemory — 结构化执行历史（超越简单双端队列）。

按 capability_type → query_pattern → success 分组存储；
提供时间窗统计、模式检测与退化检查，供 Reasoner 与 EvolutionEngine 使用。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from kernel.capability_intelligence.profile import ExecutionRecord
from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TimeWindowedStats:
    total: int = 0
    success_rate: float = 0.0
    avg_latency_ms: int = 0
    avg_quality: float = 0.0
    window_label: str = ""


@dataclass
class PatternResult:
    """检测到的执行模式。"""

    pattern: str = ""  # 例如 "data.analysis AFTER data.query"
    success_rate: float = 0.0
    sample_count: int = 0
    description: str = ""


@dataclass
class CapabilityExecutionStats:
    """单个能力类型的聚合统计。"""

    capability_type: str = ""
    total_executions: int = 0
    overall_success_rate: float = 0.0
    avg_latency_ms: int = 0
    avg_quality: float = 0.0
    windows: dict[str, TimeWindowedStats] = field(default_factory=dict)
    by_query_pattern: dict[str, dict] = field(default_factory=dict)


class ExecutionMemory:
    """结构化执行记忆，支持时间窗统计与模式检测。

    模块级单例：`execution_memory = ExecutionMemory()`
    """

    def __init__(self, max_records: int = 500) -> None:
        self._records: deque[ExecutionRecord] = deque(maxlen=max_records)
        self._by_capability: dict[str, deque[ExecutionRecord]] = {}
        # (first_cap, second_cap) -> [(success, latency), ...]
        self._sequential_patterns: dict[tuple[str, str], list[tuple[bool, int]]] = {}
        # 模式跟踪：(cap_a, cap_b) -> {strategy_type: (successes, total)}
        self._pattern_counts: dict[tuple[str, str, str], dict[str, tuple[int, int]]] = {}

    def record(self, record: ExecutionRecord) -> None:
        """存储记录并更新能力索引。"""
        self._records.append(record)
        self._by_capability.setdefault(record.capability_type, deque(maxlen=200)).append(record)

    def record_sequential(self, first: ExecutionRecord, second: ExecutionRecord) -> None:
        """记录顺序执行模式：first → second。"""
        key = (first.capability_type, second.capability_type)
        self._sequential_patterns.setdefault(key, []).append(
            (second.success, second.latency_ms)
        )
        if len(self._sequential_patterns[key]) > 100:
            self._sequential_patterns[key] = self._sequential_patterns[key][-100:]

    def get_stats(self, capability_type: str) -> CapabilityExecutionStats:
        """返回某能力的聚合统计。"""
        records = self._by_capability.get(capability_type, deque())
        if not records:
            return CapabilityExecutionStats(capability_type=capability_type)

        total = len(records)
        successes = sum(1 for r in records if r.success)
        avg_latency = sum(r.latency_ms for r in records) // total if total else 0
        avg_quality = sum(r.evidence_quality for r in records) / total if total else 0.0

        return CapabilityExecutionStats(
            capability_type=capability_type,
            total_executions=total,
            overall_success_rate=round(successes / total, 4),
            avg_latency_ms=avg_latency,
            avg_quality=round(avg_quality, 4),
        )

    def get_time_windowed_stats(
        self, capability_type: str, window_seconds: float = 3600
    ) -> TimeWindowedStats:
        """返回最近 `window_seconds` 时间窗内的记录统计。"""
        records = self._by_capability.get(capability_type, deque())
        if not records:
            return TimeWindowedStats(window_label=f"last_{int(window_seconds)}s")

        now = time.time()
        cutoff = now - window_seconds
        recent = [r for r in records if r.timestamp >= cutoff]

        if not recent:
            return TimeWindowedStats(window_label=f"last_{int(window_seconds)}s")

        total = len(recent)
        successes = sum(1 for r in recent if r.success)
        avg_latency = sum(r.latency_ms for r in recent) // total
        avg_quality = sum(r.evidence_quality for r in recent) / total

        return TimeWindowedStats(
            total=total,
            success_rate=round(successes / total, 4),
            avg_latency_ms=avg_latency,
            avg_quality=round(avg_quality, 4),
            window_label=f"last_{int(window_seconds)}s",
        )

    def detect_patterns(
        self, capability_type: str | None = None, min_samples: int = 3
    ) -> list[PatternResult]:
        """从记录数据中检测顺序执行模式。

        返回按置信度（sample_count * success_rate）排序的模式列表。
        """
        results: list[PatternResult] = []

        for (first, second), outcomes in self._sequential_patterns.items():
            if capability_type and first != capability_type:
                continue
            if len(outcomes) < min_samples:
                continue

            successes = sum(1 for s, _ in outcomes if s)
            rate = successes / len(outcomes)
            results.append(PatternResult(
                pattern=f"{second} AFTER {first}",
                success_rate=round(rate, 4),
                sample_count=len(outcomes),
                description=f"{second}在{first}之后执行，成功率{rate:.0%}（{len(outcomes)}次采样）",
            ))

        results.sort(key=lambda p: p.sample_count * p.success_rate, reverse=True)
        return results

    def degradation_check(
        self, capability_type: str, threshold: float = 0.15
    ) -> dict | None:
        """检查某能力的近期成功率是否显著下降。

        比较最近一小时成功率与整体成功率。若降幅超过 `threshold`
        则返回退化信息，否则返回 None。
        """
        records = list(self._by_capability.get(capability_type, deque()))
        if len(records) < 5:
            return None

        overall_successes = sum(1 for r in records if r.success)
        overall_rate = overall_successes / len(records)

        now = time.time()
        recent = [r for r in records if r.timestamp >= now - 3600]
        if len(recent) < 3:
            return None

        recent_successes = sum(1 for r in recent if r.success)
        recent_rate = recent_successes / len(recent)

        drop = overall_rate - recent_rate
        if drop > threshold:
            return {
                "capability_type": capability_type,
                "overall_rate": round(overall_rate, 4),
                "recent_rate": round(recent_rate, 4),
                "drop": round(drop, 4),
                "recent_samples": len(recent),
                "total_samples": len(records),
            }
        return None

    @property
    def total_records(self) -> int:
        return len(self._records)


# 模块级单例
execution_memory = ExecutionMemory()
