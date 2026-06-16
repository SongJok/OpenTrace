"""Tenant-scoped policy overrides (compliance frameworks, residency)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tenant.tenant_context import TenantContext


@dataclass
class TenantPolicy:
    tenant_id: str
    compliance_frameworks: list[str] = field(default_factory=lambda: ["soc2"])
    data_residency: str = "global"
    pii_block_export: bool = False
    max_daily_cost: float = 500.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "compliance_frameworks": list(self.compliance_frameworks),
            "data_residency": self.data_residency,
            "pii_block_export": self.pii_block_export,
            "max_daily_cost": self.max_daily_cost,
        }


class PolicyManager:
    def __init__(self) -> None:
        self._policies: dict[str, TenantPolicy] = {}

    def set_policy(self, policy: TenantPolicy) -> None:
        self._policies[policy.tenant_id] = policy

    def get_for_context(self, ctx: TenantContext) -> TenantPolicy:
        if ctx.tenant_id in self._policies:
            return self._policies[ctx.tenant_id]
        return TenantPolicy(
            tenant_id=ctx.tenant_id,
            compliance_frameworks=list(ctx.compliance_frameworks),
            data_residency=ctx.data_residency,
        )

    def apply_to_metadata(self, ctx: TenantContext, metadata: dict[str, Any]) -> dict[str, Any]:
        pol = self.get_for_context(ctx)
        md = {**ctx.to_dict(), **dict(metadata)}
        if self._policies.get(ctx.tenant_id):
            md["compliance_frameworks"] = list(pol.compliance_frameworks)
        elif not md.get("compliance_frameworks"):
            md["compliance_frameworks"] = list(pol.compliance_frameworks)
        if not md.get("data_residency") or md.get("data_residency") == "global":
            if ctx.data_residency and ctx.data_residency != "global":
                md["data_residency"] = ctx.data_residency
            else:
                md.setdefault("data_residency", pol.data_residency)
        md["tenant_policy"] = pol.to_dict()
        return md