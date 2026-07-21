"""CapabilityFeedbackLoop — 将执行结果闭环回能力画像。

CognitiveExecutive 阶段 9 批评后，记录所用能力、成败、耗时、证据质量，
并更新 profiler 的可靠性与延迟估计。

Phase 1：仅内存（deque，最多 200 条）；Phase 2：Redis 持久化。
"""

from __future__ import annotations

from collections import deque

from kernel.capability_intelligence.profile import ExecutionRecord
from kernel.capability_intelligence.profiler import CapabilityProfiler
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class CapabilityFeedbackLoop:
    """记录执行结果并回灌到能力画像。"""

    def __init__(self, profiler: CapabilityProfiler) -> None:
        self._profiler = profiler
        self._records: deque[ExecutionRecord] = deque(maxlen=200)

    def record(self, record: ExecutionRecord) -> None:
        """存储记录并立即更新该能力的画像。"""
        self._records.append(record)
        self._profiler.update_from_record(record)

    def recent_stats(self, capability_type: str, n: int = 20) -> dict:
        """返回某能力在已存储记录中的近期成功率和平均延迟。"""
        relevant = [r for r in self._records if r.capability_type == capability_type]
        recent = relevant[-n:] if len(relevant) > n else relevant

        if not recent:
            return {"success_rate": 0.0, "avg_latency_ms": 0, "count": 0}

        successes = sum(1 for r in recent if r.success)
        avg_latency = sum(r.latency_ms for r in recent) // len(recent)
        avg_quality = sum(r.evidence_quality for r in recent) / len(recent)

        return {
            "success_rate": round(successes / len(recent), 4),
            "avg_latency_ms": avg_latency,
            "avg_evidence_quality": round(avg_quality, 4),
            "count": len(recent),
        }

    @property
    def total_records(self) -> int:
        return len(self._records)
