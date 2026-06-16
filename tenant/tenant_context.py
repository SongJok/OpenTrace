"""Six-layer tenant context: Tenant → Org → Workspace → User → Session → Goal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TenantContext:
    tenant_id: str = "default"
    org_id: str = "default"
    workspace_id: str = "default"
    user_id: str = ""
    session_id: str = ""
    goal_id: str = ""
    data_residency: str = "global"
    compliance_frameworks: list[str] = field(default_factory=lambda: ["soc2"])
    tier: str = "standard"
    extra: dict[str, Any] = field(default_factory=dict)

    def isolation_key(self) -> str:
        return f"{self.tenant_id}:{self.org_id}:{self.workspace_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "data_residency": self.data_residency,
            "compliance_frameworks": list(self.compliance_frameworks),
            "tier": self.tier,
            "isolation_key": self.isolation_key(),
            **self.extra,
        }


def resolve_tenant_context(
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    org_id: str | None = None,
    workspace_id: str | None = None,
    goal_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TenantContext:
    md = metadata or {}
    tenant = str(tenant_id or md.get("tenant_id") or "default")
    org = str(org_id or md.get("org_id") or tenant)
    ws = str(workspace_id or md.get("workspace_id") or "default")
    residency = str(md.get("data_residency") or "global")
    frameworks = list(md.get("compliance_frameworks") or ["soc2"])
    tier = str(md.get("tenant_tier") or "standard")
    return TenantContext(
        tenant_id=tenant,
        org_id=org,
        workspace_id=ws,
        user_id=str(user_id or md.get("user_id") or ""),
        session_id=str(session_id or md.get("session_id") or ""),
        goal_id=str(goal_id or md.get("root_goal_id") or md.get("goal_id") or ""),
        data_residency=residency,
        compliance_frameworks=frameworks,
        tier=tier,
        extra={k: v for k, v in md.items() if k.startswith("tenant_")},
    )