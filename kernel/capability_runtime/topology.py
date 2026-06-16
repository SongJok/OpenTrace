"""Capability dependency topology."""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class CapabilityTopology:
    nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)

_DEFAULT_TOPOLOGY = CapabilityTopology(
    nodes=["data_query", "document_retrieval", "web_search", "fusion"],
    edges=[
        ("data_query", "fusion"),
        ("document_retrieval", "fusion"),
        ("web_search", "fusion"),
    ],
)

def get_default_topology() -> CapabilityTopology:
    return _DEFAULT_TOPOLOGY

def dependents_of(capability_type: str) -> list[str]:
    topo = get_default_topology()
    return [b for a, b in topo.edges if a == capability_type]