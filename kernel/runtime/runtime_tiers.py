"""Tier-1 runtime registry metadata — enterprise dispatch contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TIER1_RUNTIMES: dict[str, dict[str, Any]] = {
    "cognitive_executive": {
        "tier": 1,
        "kind": "agent",
        "requires_goal_graph": True,
        "requires_governance_prepare": True,
        "description": "Default cognitive executive (plan/execute/fuse/critic)",
    },
    "data_intelligence": {
        "tier": 1,
        "kind": "data",
        "requires_goal_graph": True,
        "requires_governance_prepare": True,
        "description": "Data intelligence runtime (SQL/semantic layer)",
    },
    "multi_goal": {
        "tier": 1,
        "kind": "orchestration",
        "requires_goal_graph": True,
        "requires_governance_prepare": True,
        "description": "Multi-question / multi-goal fan-out runtime",
    },
}


@dataclass
class RuntimeTierDescriptor:
    name: str
    tier: int = 1
    kind: str = "agent"
    requires_goal_graph: bool = True
    requires_governance_prepare: bool = True
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier,
            "kind": self.kind,
            "requires_goal_graph": self.requires_goal_graph,
            "requires_governance_prepare": self.requires_governance_prepare,
            "description": self.description,
            **self.extra,
        }


def get_runtime_tier(name: str) -> RuntimeTierDescriptor | None:
    raw = TIER1_RUNTIMES.get(name)
    if not raw:
        return None
    return RuntimeTierDescriptor(name=name, **{k: v for k, v in raw.items() if k != "extra"})


def list_tier1_runtimes() -> list[RuntimeTierDescriptor]:
    return [get_runtime_tier(n) for n in sorted(TIER1_RUNTIMES) if get_runtime_tier(n)]


def attach_tier_metadata(ctx: Any, runtime_name: str) -> None:
    desc = get_runtime_tier(runtime_name)
    if not desc or ctx is None:
        return
    ctx.metadata = getattr(ctx, "metadata", None) or {}
    ctx.metadata["runtime_tier"] = desc.to_dict()