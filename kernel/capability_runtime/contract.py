"""Capability execution contract — behavioral constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.protocol.runtime_contract import CapabilityRef


@dataclass
class CapabilityExecutionContract:
    capability_type: str
    max_latency_ms: float = 60_000.0
    requires_sandbox: bool = False
    allowed_environments: list[str] = field(default_factory=lambda: ["default"])
    min_success_rate: float = 0.0
    risk_tier: str = "low"
    cost_units: float = 1.0
    dependencies: list[str] = field(default_factory=list)
    owner_runtime: str = "cognitive_executive"
    tier: str = "standard"


_CONTRACTS: dict[str, CapabilityExecutionContract] = {
    "data_query": CapabilityExecutionContract(
        capability_type="data_query",
        max_latency_ms=120_000.0,
        requires_sandbox=False,
    ),
    "web_search": CapabilityExecutionContract(
        capability_type="web_search",
        max_latency_ms=45_000.0,
    ),
}


def get_capability_contract(capability_type: str) -> CapabilityExecutionContract:
    return _CONTRACTS.get(
        capability_type,
        CapabilityExecutionContract(capability_type=capability_type),
    )


def validate_capability_execution(ref: CapabilityRef, *, environment: str = "default") -> list[str]:
    c = get_capability_contract(ref.capability_type)
    violations: list[str] = []
    if environment not in c.allowed_environments and "default" not in c.allowed_environments:
        violations.append("environment_not_allowed")
    return violations