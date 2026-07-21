"""Capability Control Plane — unified descriptors for Registry / Planner / Governance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.capability_runtime.metadata import CapabilityRuntimeMetadata, enrich_capability_ref
from kernel.protocol.runtime_contract import CapabilityRef


@dataclass
class CapabilityDescriptor:
    """Enterprise capability registration record."""

    capability_type: str
    version: str = "1.0"
    risk_tier: str = "low"
    cost_estimate: float = 0.0
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0
    dependencies: list[str] = field(default_factory=list)
    owner_runtime: str = "cognitive_executive"
    sla_timeout_sec: int = 30
    environments: list[str] = field(default_factory=lambda: ["default"])
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_metadata(cls, meta: CapabilityRuntimeMetadata, **kwargs: Any) -> CapabilityDescriptor:
        return cls(
            capability_type=meta.capability_type,
            version=meta.version,
            risk_tier=meta.risk_tier,
            cost_estimate=meta.cost_estimate,
            avg_latency_ms=meta.avg_latency_ms,
            success_rate=meta.success_rate,
            dependencies=list(meta.dependencies),
            environments=list(meta.environments),
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_type": self.capability_type,
            "version": self.version,
            "risk_tier": self.risk_tier,
            "cost_estimate": self.cost_estimate,
            "avg_latency_ms": self.avg_latency_ms,
            "success_rate": self.success_rate,
            "dependencies": list(self.dependencies),
            "owner_runtime": self.owner_runtime,
            "sla_timeout_sec": self.sla_timeout_sec,
            "environments": list(self.environments),
            **self.extra,
        }


_REGISTRY: dict[str, CapabilityDescriptor] = {}


def _seed_defaults() -> None:
    if _REGISTRY:
        return
    from kernel.capability_runtime.metadata import list_default_capability_types, get_default_metadata

    owners = {
        "data_query": "data_intelligence",
        "document_retrieval": "cognitive_executive",
        "web_search": "cognitive_executive",
    }
    for cap in list_default_capability_types():
        meta = get_default_metadata(cap)
        if not meta:
            continue
        register_capability_descriptor(
            CapabilityDescriptor.from_metadata(
                meta,
                owner_runtime=owners.get(cap, "cognitive_executive"),
            )
        )


def register_capability_descriptor(desc: CapabilityDescriptor) -> None:
    _REGISTRY[desc.capability_type] = desc


def get_capability_descriptor(capability_type: str) -> CapabilityDescriptor | None:
    _seed_defaults()
    return _REGISTRY.get((capability_type or "").strip())


def list_capability_descriptors() -> list[CapabilityDescriptor]:
    _seed_defaults()
    return [d for d in _REGISTRY.values()]


def enrich_ref_with_descriptor(ref: CapabilityRef) -> CapabilityRef:
    """Attach control-plane fields to CapabilityRef.params."""
    ref = enrich_capability_ref(ref)
    desc = get_capability_descriptor(ref.capability_type)
    if desc:
        ref.params = dict(ref.params or {})
        ref.params["_control_plane"] = desc.to_dict()
    return ref


def rank_capabilities_for_intent(
    capability_types: list[str],
    *,
    allowed: list[str] | None = None,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Deterministic ranking: lower risk, lower cost, higher success_rate."""
    _seed_defaults()
    allow = set(allowed or [])
    scored: list[tuple[float, CapabilityDescriptor]] = []
    for cap in capability_types:
        d = get_capability_descriptor(cap)
        if not d:
            continue
        if allow and cap not in allow:
            continue
        risk_pen = {"low": 0.0, "medium": 0.15, "high": 0.4}.get(d.risk_tier, 0.2)
        score = (1.0 - risk_pen) * d.success_rate - d.cost_estimate * 0.1
        scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    out: list[dict[str, Any]] = []
    for score, desc in scored[:max_items]:
        row = desc.to_dict()
        row["score"] = round(score, 4)
        out.append(row)
    return out