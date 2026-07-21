"""Capability OS — lifecycle, SLA metrics, marketplace-style products."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.capability_runtime.lifecycle import CapabilityLifecycleState, transition_capability
from kernel.capability_runtime.capability_control_plane import (
    get_capability_descriptor,
    list_capability_descriptors,
)


@dataclass
class CapabilitySLA:
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0
    cost_per_invocation: float = 0.0
    confidence: float = 0.8
    availability: float = 1.0

    def degraded(self) -> bool:
        return self.success_rate < 0.85 or self.availability < 0.9

    def to_dict(self) -> dict[str, Any]:
        return {
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "cost_per_invocation": self.cost_per_invocation,
            "confidence": self.confidence,
            "availability": self.availability,
            "degraded": self.degraded(),
        }


@dataclass
class CapabilityProductState:
    capability_type: str
    lifecycle: str = CapabilityLifecycleState.ACTIVE.value
    product_name: str = ""
    category: str = "general"
    sla: CapabilitySLA = field(default_factory=CapabilitySLA)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_type": self.capability_type,
            "lifecycle": self.lifecycle,
            "product_name": self.product_name or self.capability_type,
            "category": self.category,
            "sla": self.sla.to_dict(),
        }


_PRODUCT_CATEGORIES = {
    "data_query": ("Data Analytics", "analytics"),
    "document_retrieval": ("Enterprise Knowledge", "knowledge"),
    "web_search": ("Market Research", "research"),
}


class CapabilityOS:
    def __init__(self) -> None:
        self._lifecycle: dict[str, CapabilityLifecycleState] = {}
        self._sla: dict[str, CapabilitySLA] = {}
        self._invocations: dict[str, list[tuple[bool, float, float]]] = {}

    def _ensure(self, capability_type: str) -> None:
        cap = (capability_type or "").strip()
        if not cap:
            return
        if cap not in self._lifecycle:
            self._lifecycle[cap] = CapabilityLifecycleState.ACTIVE
        if cap not in self._sla:
            desc = get_capability_descriptor(cap)
            if desc:
                self._sla[cap] = CapabilitySLA(
                    success_rate=desc.success_rate,
                    avg_latency_ms=desc.avg_latency_ms,
                    cost_per_invocation=desc.cost_estimate,
                )
            else:
                self._sla[cap] = CapabilitySLA()

    def set_lifecycle(self, capability_type: str, target: CapabilityLifecycleState) -> bool:
        self._ensure(capability_type)
        cur = self._lifecycle[capability_type]
        if not transition_capability(cur, target):
            return False
        self._lifecycle[capability_type] = target
        return True

    def record_invocation(
        self,
        capability_type: str,
        *,
        success: bool,
        latency_ms: float,
        cost: float,
    ) -> None:
        self._ensure(capability_type)
        hist = self._invocations.setdefault(capability_type, [])
        hist.append((success, latency_ms, cost))
        if len(hist) > 200:
            del hist[:100]
        self._recompute_sla(capability_type)

    def _recompute_sla(self, capability_type: str) -> None:
        hist = self._invocations.get(capability_type) or []
        if not hist:
            return
        n = len(hist)
        successes = sum(1 for s, _, _ in hist if s)
        avg_lat = sum(lat for _, lat, _ in hist) / n
        avg_cost = sum(c for _, _, c in hist) / n
        sla = self._sla[capability_type]
        sla.success_rate = successes / n
        sla.avg_latency_ms = avg_lat
        sla.cost_per_invocation = avg_cost
        sla.availability = sla.success_rate
        sla.confidence = min(0.99, 0.5 + sla.success_rate * 0.5)
        if sla.degraded() and self._lifecycle[capability_type] == CapabilityLifecycleState.ACTIVE:
            self._lifecycle[capability_type] = CapabilityLifecycleState.DEGRADED

    def get_product_state(self, capability_type: str) -> CapabilityProductState | None:
        cap = (capability_type or "").strip()
        if not cap:
            return None
        self._ensure(cap)
        name, cat = _PRODUCT_CATEGORIES.get(cap, (cap, "general"))
        return CapabilityProductState(
            capability_type=cap,
            lifecycle=self._lifecycle[cap].value,
            product_name=name,
            category=cat,
            sla=self._sla[cap],
        )

    def list_marketplace(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for desc in list_capability_descriptors():
            st = self.get_product_state(desc.capability_type)
            if st:
                row = st.to_dict()
                row["risk_tier"] = desc.risk_tier
                out.append(row)
        return out


_os: CapabilityOS | None = None


def get_capability_os() -> CapabilityOS:
    global _os
    if _os is None:
        _os = CapabilityOS()
    return _os