"""Enterprise world model runtime — extends kernel grounding with tenant/org/resource."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.cognition.runtime_grounding import RuntimeGroundingState, get_grounding, project_from_context
from tenant.tenant_context import TenantContext, resolve_tenant_context


@dataclass
class TenantModelSlice:
    tenant_id: str = "default"
    org_id: str = "default"
    workspace_id: str = "default"
    tier: str = "standard"
    data_residency: str = "global"


@dataclass
class OrgModelSlice:
    org_id: str = "default"
    policies: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceModelSlice:
    quota_turns_remaining: int = 10_000
    cost_budget_remaining: float = 500.0


@dataclass
class SharedWorldState:
    grounding: RuntimeGroundingState
    tenant: TenantModelSlice = field(default_factory=TenantModelSlice)
    org: OrgModelSlice = field(default_factory=OrgModelSlice)
    resource: ResourceModelSlice = field(default_factory=ResourceModelSlice)
    graph: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        base = self.grounding.to_dict()
        base["tenant_model"] = {
            "tenant_id": self.tenant.tenant_id,
            "org_id": self.tenant.org_id,
            "workspace_id": self.tenant.workspace_id,
            "tier": self.tenant.tier,
            "data_residency": self.tenant.data_residency,
        }
        base["org_model"] = {"org_id": self.org.org_id, "policies": dict(self.org.policies)}
        base["resource_model"] = {
            "quota_turns_remaining": self.resource.quota_turns_remaining,
            "cost_budget_remaining": self.resource.cost_budget_remaining,
        }
        base["world_graph"] = dict(self.graph)
        return base


class WorldGraph:
    """Lightweight edges between world entities (goal, memory, capability)."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: list[tuple[str, str, str]] = []

    def add_node(self, node_id: str, node_type: str, **attrs: Any) -> None:
        self._nodes[node_id] = {"id": node_id, "type": node_type, **attrs}

    def link(self, source: str, target: str, relation: str) -> None:
        self._edges.append((source, target, relation))

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": list(self._nodes.values()),
            "edges": [
                {"source": s, "target": t, "relation": r} for s, t, r in self._edges
            ],
        }

    @classmethod
    def from_grounding(cls, state: RuntimeGroundingState) -> WorldGraph:
        g = cls()
        root = state.goal.root_goal_id or "goal:root"
        g.add_node(root, "goal", version=state.goal.version)
        for cap in state.capability.active_capabilities:
            cid = f"cap:{cap}"
            g.add_node(cid, "capability")
            g.link(root, cid, "uses")
        for ref in state.memory.fabric_refs[:16]:
            mid = f"mem:{ref}"
            g.add_node(mid, "memory")
            g.link(root, mid, "recalls")
        return g


def build_shared_world_state(
    ctx: Any,
    *,
    tenant_ctx: TenantContext | None = None,
) -> SharedWorldState:
    grounding = project_from_context(ctx)
    tc = tenant_ctx or resolve_tenant_context(
        user_id=getattr(ctx, "user_id", None),
        session_id=getattr(ctx, "session_id", None),
        metadata=getattr(ctx, "metadata", None) or {},
    )
    tenant_slice = TenantModelSlice(
        tenant_id=tc.tenant_id,
        org_id=tc.org_id,
        workspace_id=tc.workspace_id,
        tier=tc.tier,
        data_residency=tc.data_residency,
    )
    wg = WorldGraph.from_grounding(grounding)
    return SharedWorldState(
        grounding=grounding,
        tenant=tenant_slice,
        org=OrgModelSlice(org_id=tc.org_id),
        graph=wg.to_dict(),
    )


def merge_tenant_into_grounding(session_id: str, tenant_ctx: TenantContext) -> RuntimeGroundingState:
    state = get_grounding(session_id)
    state.user.session_id = session_id
    state.user.preferences["tenant_id"] = tenant_ctx.tenant_id
    state.user.preferences["workspace_id"] = tenant_ctx.workspace_id
    state.risk.factors = list(
        set(state.risk.factors + [f"tenant:{tenant_ctx.tenant_id}"])
    )
    return state