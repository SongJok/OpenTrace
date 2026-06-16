"""Turn cost estimation — aligns tokens, capability, and billing metadata."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from tenant.billing_manager import BillingManager, CostAttribution
from tenant.tenant_context import TenantContext

logger = get_logger(__name__)

# USD per 1M tokens (rough defaults; override via settings)
_DEFAULT_PROMPT_PER_M = 0.15
_DEFAULT_COMPLETION_PER_M = 0.60


def _rates_from_settings() -> tuple[float, float]:
    try:
        from infra.config.settings import settings

        pm = float(getattr(settings, "enterprise_billing_prompt_per_million", _DEFAULT_PROMPT_PER_M) or _DEFAULT_PROMPT_PER_M)
        cm = float(
            getattr(settings, "enterprise_billing_completion_per_million", _DEFAULT_COMPLETION_PER_M)
            or _DEFAULT_COMPLETION_PER_M
        )
        return pm, cm
    except Exception:
        return _DEFAULT_PROMPT_PER_M, _DEFAULT_COMPLETION_PER_M


def estimate_cost_from_tokens(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    extra_cost: float = 0.0,
) -> float:
    pm, cm = _rates_from_settings()
    llm = (int(prompt_tokens or 0) * pm + int(completion_tokens or 0) * cm) / 1_000_000.0
    return round(float(extra_cost or 0.0) + llm, 8)


def resolve_turn_cost(metadata: dict[str, Any] | None) -> float:
    """Single source for turn cost: explicit estimated_cost, else token-derived."""
    md = dict(metadata or {})
    explicit = md.get("estimated_cost")
    if explicit is not None and str(explicit).strip() != "":
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    if md.get("turn_cost") is not None:
        try:
            return float(md["turn_cost"])
        except (TypeError, ValueError):
            pass
    return estimate_cost_from_tokens(
        prompt_tokens=int(md.get("prompt_tokens") or 0),
        completion_tokens=int(md.get("completion_tokens") or 0),
        extra_cost=float(md.get("extra_cost") or md.get("capability_cost") or 0.0),
    )


def apply_billing_to_metadata(
    metadata: dict[str, Any] | None,
    *,
    capability_type: str = "",
    goal_id: str = "",
) -> dict[str, Any]:
    """Write estimated_cost, turn_cost, billing_attribution into metadata."""
    md = dict(metadata or {})
    cost = resolve_turn_cost(md)
    md["estimated_cost"] = cost
    md["turn_cost"] = cost
    cap = capability_type or str(md.get("capability_type") or "")
    md["billing_attribution"] = {
        "capability_type": cap,
        "goal_id": goal_id or str(md.get("goal_id") or ""),
        "cost": cost,
        "prompt_tokens": int(md.get("prompt_tokens") or 0),
        "completion_tokens": int(md.get("completion_tokens") or 0),
    }
    return md


_billing_manager: BillingManager | None = None


def get_billing_manager() -> BillingManager:
    global _billing_manager
    if _billing_manager is None:
        _billing_manager = BillingManager()
    return _billing_manager


def record_turn_billing(
    ctx: TenantContext,
    *,
    metadata: dict[str, Any] | None,
    capability_type: str = "",
    session_id: str = "",
    persist_ledger: bool = True,
) -> CostAttribution:
    md = apply_billing_to_metadata(
        metadata,
        capability_type=capability_type,
        goal_id=ctx.goal_id,
    )
    cost = float(md.get("estimated_cost") or 0.0)
    cap = capability_type or str(md.get("capability_type") or "")
    attr = get_billing_manager().record_usage(
        ctx,
        capability_type=cap,
        cost=cost,
        goal_id=ctx.goal_id,
    )
    try:
        from infra.config.settings import settings

        ledger_on = bool(getattr(settings, "enterprise_billing_persist_enabled", False))
    except Exception:
        ledger_on = False
    if persist_ledger and ledger_on and cost > 0:
        try:
            import asyncio

            from tenant.billing_store import persist_ledger_entry

            async def _persist() -> None:
                await persist_ledger_entry(
                    ctx,
                    attr,
                    session_id=session_id,
                    prompt_tokens=int(md.get("prompt_tokens") or 0),
                    completion_tokens=int(md.get("completion_tokens") or 0),
                    metadata={"billing_attribution": md.get("billing_attribution")},
                )

            try:
                asyncio.get_running_loop().create_task(_persist())
            except RuntimeError:
                asyncio.run(_persist())
        except Exception as exc:
            logger.debug("billing_ledger_async_skipped", error=str(exc))
    return attr