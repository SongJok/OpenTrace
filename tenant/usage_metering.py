"""LLM / turn usage metering for cost governance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger
from tenant.tenant_context import TenantContext

logger = get_logger(__name__)


@dataclass
class UsageRecord:
    tenant_id: str
    session_id: str = ""
    goal_id: str = ""
    capability_type: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "capability_type": self.capability_type,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            **self.metadata,
        }


class UsageMeteringService:
    """In-process metering; aggregates to billing manager."""

    _COST_PER_1K_PROMPT = 0.0008
    _COST_PER_1K_COMPLETION = 0.002

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []

    def estimate_from_tokens(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        return (prompt_tokens / 1000.0) * self._COST_PER_1K_PROMPT + (
            completion_tokens / 1000.0
        ) * self._COST_PER_1K_COMPLETION

    def record_turn(
        self,
        ctx: TenantContext,
        *,
        session_id: str = "",
        goal_id: str = "",
        capability_type: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        extra_cost: float = 0.0,
        estimated_cost: float | None = None,
    ) -> UsageRecord:
        if prompt_tokens == 0 and completion_tokens == 0 and estimated_cost is None:
            prompt_tokens = int(
                getattr(settings, "kernel_default_prompt_tokens_per_turn", 800) or 800
            )
            completion_tokens = int(
                getattr(settings, "kernel_default_completion_tokens_per_turn", 400) or 400
            )
        est = (
            float(estimated_cost)
            if estimated_cost is not None
            else self.estimate_from_tokens(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            + extra_cost
        )
        rec = UsageRecord(
            tenant_id=ctx.tenant_id,
            session_id=session_id,
            goal_id=goal_id,
            capability_type=capability_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=est,
        )
        self._records.append(rec)
        if len(self._records) > 2000:
            del self._records[:1000]
        try:
            from control_plane.control_plane import get_enterprise_control_plane

            get_enterprise_control_plane().record_turn_cost(
                ctx,
                capability_type=capability_type,
                actual_cost=est,
                goal_id=goal_id,
            )
        except Exception as exc:
            logger.warning("usage_metering_billing_record_skipped", error=str(exc))
        try:
            from tenant.usage_redis_store import record_usage_delta, run_usage_coro

            run_usage_coro(
                record_usage_delta(
                    ctx.tenant_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=est,
                )
            )
        except Exception as exc:
            logger.debug("usage_metering_redis_mirror_skipped", error=str(exc))
        return rec

    def tenant_summary(self, tenant_id: str) -> dict[str, Any]:
        tid = tenant_id or "default"
        rows = [r for r in self._records if r.tenant_id == tid]
        total = sum(r.estimated_cost_usd for r in rows)
        tokens = sum(r.prompt_tokens + r.completion_tokens for r in rows)
        return {
            "tenant_id": tid,
            "turn_count": len(rows),
            "total_tokens": tokens,
            "total_estimated_cost_usd": round(total, 4),
        }

    async def tenant_summary_async(self, tenant_id: str) -> dict[str, Any]:
        local = self.tenant_summary(tenant_id)
        try:
            from tenant.usage_redis_store import read_daily_summary

            remote = await read_daily_summary(tenant_id or "default")
            if not remote:
                return local
            return {
                "tenant_id": local["tenant_id"],
                "turn_count": max(local["turn_count"], int(remote.get("turn_count", 0))),
                "total_tokens": max(
                    local["total_tokens"],
                    int(remote.get("prompt_tokens", 0)) + int(remote.get("completion_tokens", 0)),
                ),
                "total_estimated_cost_usd": round(
                    max(
                        float(local["total_estimated_cost_usd"]),
                        float(remote.get("total_estimated_cost_usd", 0)),
                    ),
                    4,
                ),
                "redis_daily": remote,
            }
        except Exception as exc:
            logger.debug("usage_summary_redis_skipped", error=str(exc))
            return local


_meter: UsageMeteringService | None = None


def get_usage_metering() -> UsageMeteringService:
    global _meter
    if _meter is None:
        _meter = UsageMeteringService()
    return _meter
