"""Tenant registration and policy binding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TenantRecord:
    tenant_id: str
    name: str = ""
    tier: str = "standard"
    data_residency: str = "global"
    compliance_frameworks: list[str] = field(default_factory=lambda: ["soc2"])
    max_monthly_cost: float = 10_000.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "tier": self.tier,
            "data_residency": self.data_residency,
            "compliance_frameworks": list(self.compliance_frameworks),
            "max_monthly_cost": self.max_monthly_cost,
            **self.metadata,
        }


_tenant_store: dict[str, TenantRecord] = {}


class TenantManager:
    def __init__(self) -> None:
        self._tenants = _tenant_store

    def register(self, record: TenantRecord) -> None:
        self._tenants[record.tenant_id] = record

    def get(self, tenant_id: str) -> TenantRecord | None:
        return self._tenants.get(tenant_id or "default")

    def ensure_default(self) -> TenantRecord:
        if "default" not in self._tenants:
            self.register(TenantRecord(tenant_id="default", name="Default Tenant"))
        return self._tenants["default"]

    def list_all(self) -> list[TenantRecord]:
        self.ensure_default()
        return list(self._tenants.values())