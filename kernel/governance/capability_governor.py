"""能力治理 — 允许/拒绝能力绑定。"""

from __future__ import annotations

from dataclasses import dataclass, field

from kernel.protocol.runtime_contract import CapabilityRef, Constraints


@dataclass
class CapabilityGovernanceResult:
    allowed: bool = True
    denied: list[str] = field(default_factory=list)


class CapabilityGovernor:
    def check(self, capability: CapabilityRef, constraints: Constraints) -> CapabilityGovernanceResult:
        name = capability.capability_type or capability.capability_name
        if constraints.disallowed_capabilities and name in constraints.disallowed_capabilities:
            return CapabilityGovernanceResult(allowed=False, denied=[name])
        if constraints.allowed_capabilities and name not in constraints.allowed_capabilities:
            return CapabilityGovernanceResult(allowed=False, denied=[name])
        return CapabilityGovernanceResult(allowed=True)