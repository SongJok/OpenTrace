"""
Feedback Collector — async event sink for the data flywheel.
"""
from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any, Optional

from infra.cache.redis_client import get_queue_redis
from infra.observability.logger import get_logger

logger = get_logger(__name__)

FEEDBACK_QUEUE_KEY = "opentrace:feedback:queue"


class FeedbackType(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    CORRECTION = "correction"
    SYSTEM = "system"


class FeedbackCollector:
    """
    Appends structured feedback events to a Redis queue
    for async processing by the evaluation / learning pipeline.
    """

    async def collect(
        self,
        session_id: str,
        query: str,
        response: str,
        feedback_type: FeedbackType,
        score: Optional[float] = None,
        correction: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        r = await get_queue_redis()
        event = json.dumps({
            "session_id": session_id,
            "query": query,
            "response": response,
            "type": feedback_type.value,
            "score": score,
            "correction": correction,
            "meta": metadata or {},
            "ts": time.time(),
        })
        await r.rpush(FEEDBACK_QUEUE_KEY, event)
        logger.info(
            "Feedback collected",
            session=session_id,
            type=feedback_type.value,
        )

    async def drain(self, batch_size: int = 100) -> list[dict[str, Any]]:
        """Pop up to batch_size events from the queue for processing."""
        r = await get_queue_redis()
        pipe = r.pipeline()
        for _ in range(batch_size):
            pipe.lpop(FEEDBACK_QUEUE_KEY)
        raw = await pipe.execute()
        return [json.loads(item) for item in raw if item]


feedback_collector = FeedbackCollector()
