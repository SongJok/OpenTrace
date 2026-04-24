"""
Message Bus — async pub/sub over Redis Streams.
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Callable, Optional

from infra.cache.redis_client import get_pubsub_redis
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class MessageBus:
    """
    Lightweight event bus using Redis Pub/Sub.
    For heavy workloads, replace with RabbitMQ via aio-pika.
    """

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        r = await get_pubsub_redis()
        payload = json.dumps({"ts": time.time(), **event})
        await r.publish(channel, payload)
        logger.debug("Event published", channel=channel)

    async def subscribe(
        self,
        channel: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        r = await get_pubsub_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        logger.info("Subscribed to channel", channel=channel)
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await handler(data)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Handler error", channel=channel, error=str(exc))


bus = MessageBus()
