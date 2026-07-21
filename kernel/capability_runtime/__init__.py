"""Capability OS runtime — contract, lifecycle, topology, selection."""

from kernel.capability_runtime.contract import (
    get_capability_contract,
    validate_capability_execution,
)
from kernel.capability_runtime.lifecycle import (
    CapabilityLifecycleState,
    transition_capability,
)
from kernel.capability_runtime.metadata import enrich_capability_ref
from kernel.capability_runtime.selector import rank_capabilities_for_intent
from kernel.capability_runtime.topology import dependents_of, get_default_topology

__all__ = [
    "CapabilityLifecycleState",
    "dependents_of",
    "enrich_capability_ref",
    "get_capability_contract",
    "get_default_topology",
    "rank_capabilities_for_intent",
    "transition_capability",
    "validate_capability_execution",
]