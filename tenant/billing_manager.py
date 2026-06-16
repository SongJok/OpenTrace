"""Cost attribution per tenant / goal / capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tenant.tenant_context import TenantContext


@dataclass
class CostAttribution:
    tenant_id: str
    capability_type: str = ""
    goal_id: str = ""
    cost: float = 0.0
    currency: str = "USD"
    dimensions: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "capability_type": self.capability_type,
            "goal_id": self.goal_id,
            "cost": round(self.cost, 6),
            "currency": self.currency,
            "dimensions": dict(self.dimensions),
        }


class BillingManager:
    def __init__(self) -> None:
        self._by_tenant: dict[str, float] = {}
        self._by_goal: dict[str, float] = {}
        self._by_capability: dict[str, float] = {}

    def attribute_turn(
        self,
        ctx: TenantContext,
        *,
        capability_type: str = "",
        estimated_cost: float = 0.0,
    ) -> CostAttribution:
        return CostAttribution(
            tenant_id=ctx.tenant_id,
            capability_type=capability_type,
            goal_id=ctx.goal_id,
            cost=estimated_cost,
            dimensions={
                "estimated": estimated_cost,
            },
        )

    def record_usage(
        self,
        ctx: TenantContext,
        *,
        capability_type: str,
        cost: float,
        goal_id: str = "",
    ) -> CostAttribution:
        tid = ctx.tenant_id
        self._by_tenant[tid] = self._by_tenant.get(tid, 0.0) + cost
        gid = goal_id or ctx.goal_id
        if gid:
            self._by_goal[gid] = self._by_goal.get(gid, 0.0) + cost
        if capability_type:
            self._by_capability[capability_type] = (
                self._by_capability.get(capability_type, 0.0) + cost
            )
        return CostAttribution(
            tenant_id=tid,
            capability_type=capability_type,
            goal_id=gid,
            cost=cost,
            dimensions={
                "tenant_total": self._by_tenant[tid],
                "goal_total": self._by_goal.get(gid, 0.0),
            },
        )

    def snapshot(self, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "total_cost": self._by_tenant.get(tenant_id, 0.0),
            "by_goal": {k: v for k, v in self._by_goal.items()},
            "by_capability": {
                k: v for k, v in self._by_capability.items()
            },
        }

    async def persist_snapshot_as_invoice(
        self,
        tenant_id: str,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        status: str = "draft",
    ) -> str | None:
        """Write in-memory totals to billing_invoices (requires migration)."""
        from datetime import datetime, timezone

        from tenant.billing_store import persist_invoice_snapshot, snapshot_to_invoice_lines

        snap = self.snapshot(tenant_id)
        now = datetime.now(timezone.utc)
        ps = period_start or now
        pe = period_end or now
        lines = snapshot_to_invoice_lines(snap, tenant_id=tenant_id)
        return await persist_invoice_snapshot(
            tenant_id,
            period_start=ps,
            period_end=pe,
            total_usd=float(snap.get("total_cost") or 0.0),
            line_items=lines,
            status=status,
        )