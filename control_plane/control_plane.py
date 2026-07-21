"""Unified enterprise control plane facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tenant.tenant_context import TenantContext, resolve_tenant_context
from tenant.quota_manager import QuotaManager, QuotaDecision
from tenant.billing_manager import BillingManager, CostAttribution
from kernel.governance.compliance_runtime import ComplianceRuntime, ComplianceDecision
from kernel.capability_runtime.capability_os import get_capability_os


@dataclass
class ControlPlaneDecision:
    allowed: bool
    violations: list[str] = field(default_factory=list)
    tenant: dict[str, Any] = field(default_factory=dict)
    quota: dict[str, Any] = field(default_factory=dict)
    compliance: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    capability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "violations": list(self.violations),
            "tenant": dict(self.tenant),
            "quota": dict(self.quota),
            "compliance": dict(self.compliance),
            "cost": dict(self.cost),
            "capability": dict(self.capability),
        }


class EnterpriseControlPlane:
    """Orchestrates tenant isolation, quotas, compliance, and capability products."""

    def __init__(self) -> None:
        self._quota = QuotaManager()
        self._billing = BillingManager()
        self._compliance = ComplianceRuntime()
        self._capability_os = get_capability_os()

    def evaluate_turn(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
        capability_type: str = "",
        estimated_cost: float = 0.0,
        pii_detected: bool = False,
        data_region: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ControlPlaneDecision:
        ctx = resolve_tenant_context(
            user_id=user_id,
            session_id=session_id,
            tenant_id=tenant_id,
            org_id=org_id,
            workspace_id=workspace_id,
            metadata=metadata,
        )
        violations: list[str] = []
        quota_dec: QuotaDecision = self._quota.check_turn(ctx, estimated_cost=estimated_cost)
        if not quota_dec.allowed:
            violations.extend(quota_dec.violations)

        comp: ComplianceDecision = self._compliance.evaluate_turn(
            pii_detected=pii_detected,
            data_region=data_region or ctx.data_residency,
            frameworks=ctx.compliance_frameworks,
        )
        if not comp.allowed:
            violations.extend(comp.violations)

        cap_state = self._capability_os.get_product_state(capability_type) if capability_type else None
        if cap_state and cap_state.lifecycle in ("retired", "deprecated"):
            violations.append(f"capability_{cap_state.lifecycle}:{capability_type}")
        elif cap_state and cap_state.lifecycle == "degraded":
            # Warn-only: SLA degraded does not block; surfaced in capability dict
            pass

        cost_attr = self._billing.attribute_turn(
            ctx,
            capability_type=capability_type,
            estimated_cost=estimated_cost,
        )

        allowed = len(violations) == 0
        return ControlPlaneDecision(
            allowed=allowed,
            violations=violations,
            tenant=ctx.to_dict(),
            quota=quota_dec.to_dict(),
            compliance=comp.to_dict(),
            cost=cost_attr.to_dict(),
            capability=cap_state.to_dict() if cap_state else {},
        )

    async def evaluate_turn_async(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
        capability_type: str = "",
        estimated_cost: float = 0.0,
        pii_detected: bool = False,
        data_region: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ControlPlaneDecision:
        """Async quota path — reads Redis usage/limits when enterprise_quota_redis_enabled."""
        ctx = resolve_tenant_context(
            user_id=user_id,
            session_id=session_id,
            tenant_id=tenant_id,
            org_id=org_id,
            workspace_id=workspace_id,
            metadata=metadata,
        )
        violations: list[str] = []
        quota_dec = await self._quota.check_turn_async(ctx, estimated_cost=estimated_cost)
        if not quota_dec.allowed:
            violations.extend(quota_dec.violations)

        comp = self._compliance.evaluate_turn(
            pii_detected=pii_detected,
            data_region=data_region or ctx.data_residency,
            frameworks=ctx.compliance_frameworks,
        )
        if not comp.allowed:
            violations.extend(comp.violations)

        cap_state = self._capability_os.get_product_state(capability_type) if capability_type else None
        if cap_state and cap_state.lifecycle in ("retired", "deprecated"):
            violations.append(f"capability_{cap_state.lifecycle}:{capability_type}")

        cost_attr = self._billing.attribute_turn(
            ctx,
            capability_type=capability_type,
            estimated_cost=estimated_cost,
        )
        allowed = len(violations) == 0
        return ControlPlaneDecision(
            allowed=allowed,
            violations=violations,
            tenant=ctx.to_dict(),
            quota=quota_dec.to_dict(),
            compliance=comp.to_dict(),
            cost=cost_attr.to_dict(),
            capability=cap_state.to_dict() if cap_state else {},
        )

    def set_quota_limits(
        self,
        ctx: TenantContext,
        *,
        daily_turns: int,
        daily_cost: float,
    ) -> None:
        self._quota.set_limits(
            ctx.isolation_key(),
            daily_turns=daily_turns,
            daily_cost=daily_cost,
        )

    def consume_turn_quota(self, ctx: TenantContext, *, cost: float = 0.0) -> None:
        """Public quota consumption after an allowed turn."""
        self._quota.consume(ctx, cost=cost)

    async def consume_turn_quota_async(self, ctx: TenantContext, *, cost: float = 0.0) -> QuotaDecision:
        """Prefer atomic Redis reserve when enterprise_quota_redis_enabled."""
        return await self._quota.consume_async(ctx, cost=cost)

    def record_turn_cost(
        self,
        ctx: TenantContext,
        *,
        capability_type: str,
        actual_cost: float,
        goal_id: str = "",
    ) -> CostAttribution:
        return self._billing.record_usage(
            ctx,
            capability_type=capability_type,
            cost=actual_cost,
            goal_id=goal_id,
        )


_cp: EnterpriseControlPlane | None = None


def get_enterprise_control_plane() -> EnterpriseControlPlane:
    global _cp
    if _cp is None:
        _cp = EnterpriseControlPlane()
    return _cp