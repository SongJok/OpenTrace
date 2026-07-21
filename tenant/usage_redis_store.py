"""Optional Redis aggregates for tenant usage metering (multi-replica)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)

_NS = "opentrace:usage"


def _day_suffix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def daily_key(tenant_id: str) -> str:
    return f"{_NS}:daily:{tenant_id or 'default'}:{_day_suffix()}"


def _enabled() -> bool:
    try:
        from infra.config.settings import settings

        return bool(getattr(settings, "enterprise_usage_redis_enabled", False))
    except Exception as exc:
        logger.debug("usage_redis_flag_skipped", error=str(exc))
        return False


async def record_usage_delta(
    tenant_id: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    turn_delta: int = 1,
) -> None:
    if not _enabled():
        return
    try:
        from infra.cache.redis_client import get_cache_redis

        r = await get_cache_redis()
        k = daily_key(tenant_id)
        pipe = r.pipeline()
        pipe.hincrby(k, "turn_count", int(turn_delta))
        pipe.hincrby(k, "prompt_tokens", int(prompt_tokens))
        pipe.hincrby(k, "completion_tokens", int(completion_tokens))
        pipe.hincrbyfloat(k, "cost_usd", float(cost_usd))
        pipe.expire(k, 172800)
        await pipe.execute()
    except Exception as exc:
        logger.warning("usage_redis_record_failed", tenant_id=tenant_id, error=str(exc))


async def read_daily_summary(tenant_id: str) -> dict[str, Any] | None:
    if not _enabled():
        return None
    try:
        from infra.cache.redis_client import get_cache_redis

        r = await get_cache_redis()
        data = await r.hgetall(daily_key(tenant_id))
        if not data:
            return None

        def _int_field(name: str) -> int:
            for k in (name, name.encode()):
                if k in data:
                    return int(float(data[k] or 0))
            return 0

        def _float_field(name: str) -> float:
            for k in (name, name.encode()):
                if k in data:
                    return float(data[k] or 0)
            return 0.0

        return {
            "turn_count": _int_field("turn_count"),
            "prompt_tokens": _int_field("prompt_tokens"),
            "completion_tokens": _int_field("completion_tokens"),
            "total_estimated_cost_usd": round(_float_field("cost_usd"), 4),
        }
    except Exception as exc:
        logger.warning("usage_redis_read_failed", tenant_id=tenant_id, error=str(exc))
        return None


def run_usage_coro(coro: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        try:
            asyncio.run(coro)
        except Exception as exc:
            logger.warning("usage_redis_async_run_failed", error=str(exc))