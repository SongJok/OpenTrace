"""
Data Flywheel — processes queued feedback and stores training examples.
"""
from __future__ import annotations

from typing import Any

from evolution.feedback.collector import FeedbackCollector
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class DataFlywheel:
    """
    Async worker that drains the feedback queue and
    persists high-quality examples for future fine-tuning.
    """

    def __init__(self) -> None:
        self._collector = FeedbackCollector()
        self._examples: list[dict[str, Any]] = []

    async def process_batch(self, batch_size: int = 100) -> int:
        events = await self._collector.drain(batch_size=batch_size)
        accepted = 0
        for event in events:
            if self._is_high_quality(event):
                self._examples.append(event)
                accepted += 1
        logger.info("Flywheel batch", total=len(events), accepted=accepted)
        return accepted

    def _is_high_quality(self, event: dict[str, Any]) -> bool:
        score = event.get("score")
        if score is not None and float(score) >= 0.8:
            return True
        if event.get("type") in ("thumbs_up", "correction"):
            return True
        return False

    def get_examples(self) -> list[dict[str, Any]]:
        return list(self._examples)

    def clear(self) -> None:
        self._examples.clear()


flywheel = DataFlywheel()
