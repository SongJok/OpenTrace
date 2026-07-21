"""Optional Redis-backed daily quota counters (multi-replica safe when enabled)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)

_NS = "opentrace:quota"


def _day_suffix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def turns_key(isolation_key: str) -> str:
    return f"{_NS}:turns:{isolation_key}:{_day_suffix()}"


def cost_key(isolation_key: str) -> str:
    return f"{_NS}:cost:{isolation_key}:{_day_suffix()}"


def limits_key(isolation_key: str) -> str:
    return f"{_NS}:limits:{isolation_key}"


def _redis_enabled() -> bool:
    try:
        from infra.config.settings import settings

        return bool(getattr(settings, "enterprise_quota_redis_enabled", False))
    except Exception as exc:
        logger.debug("quota_redis_flag_read_skipped", error=str(exc))
        return False


def redis_is_authoritative() -> bool:
    """When True, check/consume must not rely on in-process counters alone."""
    return _redis_enabled()


# Atomic: read turns/cost + limits, deny if over cap, else INCR + INCRBYFLOAT.
_RESERVE_LUA = """
local tk = KEYS[1]
local ck = KEYS[2]
local lk = KEYS[3]
local est = tonumber(ARGV[1])
local max_turns = tonumber(ARGV[2])
local max_cost = tonumber(ARGV[3])
local turns = tonumber(redis.call('GET', tk) or '0')
local cost = tonumber(redis.call('GET', ck) or '0')
if turns >= max_turns then
  return {0, 'quota_daily_turns_exceeded', turns, cost}
end
if cost + est > max_cost then
  return {0, 'quota_daily_cost_exceeded', turns, cost}
end
turns = redis.call('INCR', tk)
cost = tonumber(redis.call('INCRBYFLOAT', ck, est))
redis.call('EXPIRE', tk, 172800)
redis.call('EXPIRE', ck, 172800)
return {1, '', turns, cost}
"""


async def read_usage(isolation_key: str) -> tuple[int, float]:
    if not _redis_enabled():
        return 0, 0.0
    try:
        from infra.cache.redis_client import get_cache_redis

        r = await get_cache_redis()
        tk, ck = turns_key(isolation_key), cost_key(isolation_key)
        turns_raw, cost_raw = await asyncio.gather(r.get(tk), r.get(ck))
        turns = int(turns_raw or 0)
        cost = float(cost_raw or 0.0)
        return turns, cost
    except Exception as exc:
        logger.warning("quota_redis_read_failed", isolation_key=isolation_key, error=str(exc))
        return 0, 0.0


async def read_limits(isolation_key: str) -> dict[str, float] | None:
    if not _redis_enabled():
        return None
    try:
        from infra.cache.redis_client import get_cache_redis

        r = await get_cache_redis()
        data = await r.hgetall(limits_key(isolation_key))
        if not data:
            return None

        def _field(name: str) -> float:
            for k in (name, name.encode()):
                if k in data:
                    return float(data[k] or 0)
            return 0.0

        return {"daily_turns": _field("daily_turns"), "daily_cost": _field("daily_cost")}
    except Exception as exc:
        logger.warning("quota_redis_limits_read_failed", error=str(exc))
        return None


async def write_limits(isolation_key: str, *, daily_turns: int, daily_cost: float) -> None:
    if not _redis_enabled():
        return
    try:
        from infra.cache.redis_client import get_cache_redis

        r = await get_cache_redis()
        lk = limits_key(isolation_key)
        await r.hset(
            lk,
            mapping={"daily_turns": str(daily_turns), "daily_cost": str(daily_cost)},
        )
    except Exception as exc:
        logger.warning("quota_redis_limits_write_failed", error=str(exc))


async def consume_usage(isolation_key: str, *, cost: float) -> None:
    if not _redis_enabled():
        return
    try:
        from infra.cache.redis_client import get_cache_redis

        r = await get_cache_redis()
        tk, ck = turns_key(isolation_key), cost_key(isolation_key)
        pipe = r.pipeline()
        pipe.incr(tk)
        pipe.incrbyfloat(ck, float(cost))
        pipe.expire(tk, 172800)
        pipe.expire(ck, 172800)
        await pipe.execute()
    except Exception as exc:
        logger.warning("quota_redis_consume_failed", isolation_key=isolation_key, error=str(exc))


async def reserve_turn_quota(
    isolation_key: str,
    *,
    estimated_cost: float,
    max_turns: int,
    max_cost: float,
) -> tuple[bool, list[str], int, float]:
    """Atomically reserve one turn + cost if within daily limits."""
    if not _redis_enabled():
        return True, [], 0, 0.0
    try:
        from infra.cache.redis_client import get_cache_redis

        r = await get_cache_redis()
        tk, ck, lk = turns_key(isolation_key), cost_key(isolation_key), limits_key(isolation_key)
        raw = await r.eval(
            _RESERVE_LUA,
            3,
            tk,
            ck,
            lk,
            str(float(estimated_cost)),
            str(int(max_turns)),
            str(float(max_cost)),
        )
        if not raw or len(raw) < 4:
            return False, ["quota_redis_eval_failed"], 0, 0.0
        ok = int(raw[0]) == 1
        violation = str(raw[1] or "")
        turns = int(raw[2] or 0)
        cost = float(raw[3] or 0.0)
        violations = [violation] if violation else []
        return ok, violations, turns, cost
    except Exception as exc:
        logger.warning("quota_redis_reserve_failed", isolation_key=isolation_key, error=str(exc))
        return False, ["quota_redis_unavailable"], 0, 0.0


def run_quota_coro(coro: Any) -> None:
    """Best-effort run async quota IO from sync control plane."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        try:
            asyncio.run(coro)
        except Exception as exc:
            logger.warning("quota_redis_async_run_failed", error=str(exc))


def sync_reserve_turn_quota(
    isolation_key: str,
    *,
    estimated_cost: float,
    max_turns: int,
    max_cost: float,
) -> tuple[bool, list[str], int, float] | None:
    """Sync atomic reserve when no running loop (finalize_turn / sync workers)."""
    if not _redis_enabled():
        return None
    try:
        asyncio.get_running_loop()
        return None
    except RuntimeError:
        pass
    try:
        return asyncio.run(
            reserve_turn_quota(
                isolation_key,
                estimated_cost=estimated_cost,
                max_turns=max_turns,
                max_cost=max_cost,
            )
        )
    except Exception as exc:
        logger.warning("quota_redis_sync_reserve_failed", error=str(exc))
        return False, ["quota_redis_unavailable"], 0, 0.0


def sync_read_usage(isolation_key: str) -> tuple[int, float] | None:
    """Read Redis usage when no event loop is running (tests / sync workers)."""
    if not _redis_enabled():
        return None
    try:
        asyncio.get_running_loop()
        return None
    except RuntimeError:
        pass
    try:
        return asyncio.run(read_usage(isolation_key))
    except Exception as exc:
        logger.warning("quota_redis_sync_read_failed", error=str(exc))
        return None