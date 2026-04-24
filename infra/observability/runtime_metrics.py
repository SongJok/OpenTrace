from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any


class RuntimeMetricsStore:
    def __init__(self, window_size: int = 200) -> None:
        self._window_size = max(20, int(window_size))
        self._records: deque[dict[str, Any]] = deque(maxlen=self._window_size)
        self._lock = Lock()

    def record(self, metrics: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(dict(metrics or {}))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            items = list(self._records)

        count = len(items)
        if count == 0:
            return {
                "samples": 0,
                "avg_agent_latency_ms": 0,
                "avg_first_token_ms": 0,
                "avg_orchestrator_latency_ms": 0,
                "supervisor_retry_total": 0,
            }

        def _avg(key: str) -> int:
            vals = [int(it.get(key, 0) or 0) for it in items]
            return int(sum(vals) / max(1, len(vals)))

        return {
            "samples": count,
            "avg_agent_latency_ms": _avg("avg_agent_latency_ms"),
            "avg_first_token_ms": _avg("first_token_ms"),
            "avg_orchestrator_latency_ms": _avg("orchestrator_latency_ms"),
            "supervisor_retry_total": sum(int(it.get("supervisor_retry_count", 0) or 0) for it in items),
        }


runtime_metrics_store = RuntimeMetricsStore()
