"""Per-tenant turn and cost quotas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger
from tenant.tenant_context import TenantContext

logger = get_logger(__name__)

_DEFAULT_DAILY_TURNS = 10_000
_DEFAULT_DAILY_COST = 500.0


@dataclass
class QuotaDecision:
    allowed: bool
    violations: list[str] = field(default_factory=list)
    turns_used: int = 0
    cost_used: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "violations": list(self.violations),
            "turns_used": self.turns_used,
            "cost_used": self.cost_used,
        }


_quota_turns: dict[str, int] = {}
_quota_cost: dict[str, float] = {}
_quota_limits: dict[str, dict[str, float]] = {}


class QuotaManager:
    def __init__(self) -> None:
        self._turns = _quota_turns
        self._cost = _quota_cost
        self._limits = _quota_limits

    def set_limits(self, isolation_key: str, *, daily_turns: int, daily_cost: float) -> None:
        self._limits[isolation_key] = {
            "daily_turns": float(daily_turns),
            "daily_cost": daily_cost,
        }
        try:
            from tenant.quota_redis_store import run_quota_coro, write_limits

            run_quota_coro(write_limits(isolation_key, daily_turns=daily_turns, daily_cost=daily_cost))
        except Exception as exc:
            logger.debug("quota_limits_redis_mirror_skipped", error=str(exc))

    def _usage_for_key(self, key: str) -> tuple[int, float]:
        try:
            from tenant.quota_redis_store import redis_is_authoritative, sync_read_usage

            if redis_is_authoritative():
                remote = sync_read_usage(key)
                if remote is not None:
                    return remote
                return 0, 0.0
        except Exception as exc:
            logger.debug("quota_usage_redis_read_skipped", error=str(exc))

        turns = self._turns.get(key, 0)
        cost = self._cost.get(key, 0.0)
        try:
            from tenant.quota_redis_store import sync_read_usage

            remote = sync_read_usage(key)
            if remote is not None:
                r_turns, r_cost = remote
                turns = max(turns, r_turns)
                cost = max(cost, r_cost)
        except Exception as exc:
            logger.debug("quota_usage_redis_read_skipped", error=str(exc))
        return turns, cost

    def _limits_for_key(self, key: str) -> dict[str, float]:
        return dict(self._limits.get(key, {}))

    def _decide(
        self,
        *,
        key: str,
        lim: dict[str, float],
        turns: int,
        cost: float,
        estimated_cost: float,
    ) -> QuotaDecision:
        max_turns = int(lim.get("daily_turns", _DEFAULT_DAILY_TURNS))
        max_cost = float(lim.get("daily_cost", _DEFAULT_DAILY_COST))
        violations: list[str] = []
        if turns >= max_turns:
            violations.append("quota_daily_turns_exceeded")
        if cost + estimated_cost > max_cost:
            violations.append("quota_daily_cost_exceeded")
        return QuotaDecision(
            allowed=len(violations) == 0,
            violations=violations,
            turns_used=turns,
            cost_used=cost,
        )

    def check_turn(self, ctx: TenantContext, *, estimated_cost: float = 0.0) -> QuotaDecision:
        key = ctx.isolation_key()
        lim = self._limits_for_key(key)
        turns, cost = self._usage_for_key(key)
        return self._decide(key=key, lim=lim, turns=turns, cost=cost, estimated_cost=estimated_cost)

    async def check_turn_async(
        self, ctx: TenantContext, *, estimated_cost: float = 0.0
    ) -> QuotaDecision:
        key = ctx.isolation_key()
        lim = dict(self._limits_for_key(key))
        try:
            from tenant.quota_redis_store import read_limits, read_usage, redis_is_authoritative

            remote_lim = await read_limits(key)
            if remote_lim:
                lim.update(remote_lim)
            if redis_is_authoritative():
                turns, cost = await read_usage(key)
            else:
                turns, cost = self._usage_for_key(key)
                r_turns, r_cost = await read_usage(key)
                turns = max(turns, r_turns)
                cost = max(cost, r_cost)
        except Exception as exc:
            logger.debug("quota_check_async_redis_skipped", error=str(exc))
            turns, cost = self._usage_for_key(key)
        return self._decide(key=key, lim=lim, turns=turns, cost=cost, estimated_cost=estimated_cost)

    def _limits_for_decision(self, key: str) -> dict[str, float]:
        lim = self._limits_for_key(key)
        return {
            "daily_turns": float(lim.get("daily_turns", _DEFAULT_DAILY_TURNS)),
            "daily_cost": float(lim.get("daily_cost", _DEFAULT_DAILY_COST)),
        }

    def consume(self, ctx: TenantContext, *, cost: float = 0.0) -> None:
        key = ctx.isolation_key()
        lim = self._limits_for_decision(key)
        try:
            from tenant.quota_redis_store import (
                redis_is_authoritative,
                reserve_turn_quota,
                run_quota_coro,
                sync_reserve_turn_quota,
            )

            if redis_is_authoritative():
                result = sync_reserve_turn_quota(
                    key,
                    estimated_cost=float(cost),
                    max_turns=int(lim["daily_turns"]),
                    max_cost=float(lim["daily_cost"]),
                )
                if result is None:
                    run_quota_coro(
                        reserve_turn_quota(
                            key,
                            estimated_cost=float(cost),
                            max_turns=int(lim["daily_turns"]),
                            max_cost=float(lim["daily_cost"]),
                        )
                    )
                elif not result[0]:
                    logger.warning(
                        "quota_redis_reserve_denied",
                        isolation_key=key,
                        violations=result[1],
                    )
                return
        except Exception as exc:
            logger.debug("quota_consume_redis_reserve_skipped", error=str(exc))

        self._turns[key] = self._turns.get(key, 0) + 1
        self._cost[key] = self._cost.get(key, 0.0) + cost
        try:
            from tenant.quota_redis_store import consume_usage, run_quota_coro

            run_quota_coro(consume_usage(key, cost=float(cost)))
        except Exception as exc:
            logger.debug("quota_consume_redis_mirror_skipped", error=str(exc))

    async def consume_async(self, ctx: TenantContext, *, cost: float = 0.0) -> QuotaDecision:
        """Atomic consume when Redis is authoritative; otherwise mirrors consume()."""
        key = ctx.isolation_key()
        lim = self._limits_for_decision(key)
        try:
            from tenant.quota_redis_store import read_limits, redis_is_authoritative, reserve_turn_quota

            remote_lim = await read_limits(key)
            if remote_lim:
                lim["daily_turns"] = float(remote_lim.get("daily_turns", lim["daily_turns"]))
                lim["daily_cost"] = float(remote_lim.get("daily_cost", lim["daily_cost"]))

            if redis_is_authoritative():
                ok, violations, turns, used_cost = await reserve_turn_quota(
                    key,
                    estimated_cost=float(cost),
                    max_turns=int(lim["daily_turns"]),
                    max_cost=float(lim["daily_cost"]),
                )
                return QuotaDecision(
                    allowed=ok,
                    violations=violations,
                    turns_used=turns,
                    cost_used=used_cost,
                )
        except Exception as exc:
            logger.debug("quota_consume_async_skipped", error=str(exc))

        self.consume(ctx, cost=cost)
        turns, used = self._usage_for_key(key)
        return QuotaDecision(allowed=True, turns_used=turns, cost_used=used)