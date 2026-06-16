"""面向运行时的能力元数据 — 供治理与选型使用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.protocol.runtime_contract import CapabilityRef


@dataclass
class CapabilityRuntimeMetadata:
    capability_type: str
    version: str = "1.0"
    risk_tier: str = "low"
    cost_estimate: float = 0.0
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0
    dependencies: list[str] = field(default_factory=list)
    environments: list[str] = field(default_factory=lambda: ["default"])


_DEFAULTS: dict[str, CapabilityRuntimeMetadata] = {
    "data_query": CapabilityRuntimeMetadata(
        capability_type="data_query",
        risk_tier="medium",
        cost_estimate=0.3,
    ),
    "document_retrieval": CapabilityRuntimeMetadata(
        capability_type="document_retrieval",
        risk_tier="low",
    ),
    "web_search": CapabilityRuntimeMetadata(
        capability_type="web_search",
        risk_tier="medium",
        cost_estimate=0.2,
    ),
}


def list_default_capability_types() -> list[str]:
    return list(_DEFAULTS.keys())


def get_default_metadata(capability_type: str) -> CapabilityRuntimeMetadata | None:
    return _DEFAULTS.get(capability_type)


def enrich_capability_ref(ref: CapabilityRef) -> CapabilityRef:
    meta = _DEFAULTS.get(ref.capability_type)
    if meta:
        ref.params = dict(ref.params or {})
        ref.params["_runtime_meta"] = {
            "version": meta.version,
            "risk_tier": meta.risk_tier,
            "cost_estimate": meta.cost_estimate,
        }
    return ref