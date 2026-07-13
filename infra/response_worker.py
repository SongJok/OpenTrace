"""Durable background Responses worker loop.

The infrastructure worker intentionally does not import the gateway package.
It discovers the response job repository lazily at runtime, preserving the
agents -> infra dependency direction enforced by the architecture tests.
"""

from __future__ import annotations

import asyncio

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)


async def response_job_loop() -> None:
    interval = max(0.25, float(getattr(settings, "response_worker_poll_seconds", 2.0)))
    batch_size = max(1, int(getattr(settings, "response_worker_batch_size", 20)))
    while True:
        try:
            # Import only while the application is running; static package
            # boundaries remain gateway-independent for agents and tooling.
            from gateway.api_gateway.routers.responses import recover_queued_background_responses

            await recover_queued_background_responses(limit=batch_size)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            logger.warning("response_worker_poll_failed", error=str(exc))
        await asyncio.sleep(interval)

