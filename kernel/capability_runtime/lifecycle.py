"""Capability lifecycle states."""

from __future__ import annotations

from enum import Enum

class CapabilityLifecycleState(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEGRADED = "degraded"
    DEPRECATED = "deprecated"
    RETIRED = "retired"

def transition_capability(state: CapabilityLifecycleState, target: CapabilityLifecycleState) -> bool:
    order = [
        CapabilityLifecycleState.DRAFT,
        CapabilityLifecycleState.ACTIVE,
        CapabilityLifecycleState.DEGRADED,
        CapabilityLifecycleState.DEPRECATED,
        CapabilityLifecycleState.RETIRED,
    ]
    try:
        return order.index(target) >= order.index(state)
    except ValueError:
        return False