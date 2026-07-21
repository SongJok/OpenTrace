"""Compatibility import for the durable Responses worker."""

from __future__ import annotations

import asyncio

async def response_job_loop() -> None:
    from infra.responses.worker import response_worker_loop

    await response_worker_loop()
