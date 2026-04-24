from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class PlanMemoryRecord:
    intent: str
    query_type: str
    subtasks: list[str] = field(default_factory=list)
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class PlanMemory:
    def __init__(self, window_size: int = 50) -> None:
        self._records: deque[PlanMemoryRecord] = deque(maxlen=max(10, int(window_size)))
        self._lock = Lock()

    def add(self, record: PlanMemoryRecord) -> None:
        with self._lock:
            self._records.append(record)

    def size(self) -> int:
        with self._lock:
            return len(self._records)

    def recent_successful_plans(self, query_type: str, limit: int = 3) -> list[PlanMemoryRecord]:
        with self._lock:
            items = [r for r in self._records if r.query_type == query_type and r.score >= 0.7]
        return items[-max(1, limit):]


plan_memory = PlanMemory()
