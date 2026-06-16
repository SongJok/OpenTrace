"""Sync manifest → capability contracts, topology, and registry governance metadata."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from kernel.agent_runtime.manifest import AgentTopologyManifest, get_manifest

logger = get_logger(__name__)

_synced = False


def sync_manifest_to_runtime(*, force: bool = False) -> dict[str, Any]:
    """Idempotent: push manifest contracts/topology into capability runtime modules."""
    global _synced
    if _synced and not force:
        return {"skipped": True}

    manifest = get_manifest()
    contract_count = _sync_contracts(manifest)
    edge_count = _sync_topology(manifest)
    _synced = True
    summary = {
        "manifest_version": manifest.version,
        "contracts_synced": contract_count,
        "topology_edges": edge_count,
        "tier1_bootstrap": list(manifest.bootstrap_agent_types),
        "tier2_nodes": list(manifest.tier2_node_keys()),
    }
    logger.info("Agent topology manifest synced", **summary)
    return summary


def _sync_contracts(manifest: AgentTopologyManifest) -> int:
    from kernel.capability_runtime import contract as contract_mod

    count = 0
    seen: set[str] = set()
    for ent in manifest.entries.values():
        if ent.runtime == "tier2":
            continue
        ctype = ent.capability_type
        if ctype in seen:
            continue
        seen.add(ctype)
        c = ent.contract
        contract_mod._CONTRACTS[ctype] = contract_mod.CapabilityExecutionContract(
            capability_type=ctype,
            max_latency_ms=float(c.max_latency_ms),
            risk_tier=c.risk_tier,
            dependencies=list(c.dependencies),
            owner_runtime=ent.owner_runtime,
            tier="tier1" if ent.runtime == "tier1" else "tier2",
        )
        count += 1
    return count


def _sync_topology(manifest: AgentTopologyManifest) -> int:
    from kernel.capability_runtime import topology as topo_mod

    nodes: list[str] = []
    edges: list[tuple[str, str]] = []
    for a, b in manifest.topology_edges:
        if a:
            nodes.append(a)
        if b:
            nodes.append(b)
        if a and b:
            edges.append((a, b))
    for ent in manifest.entries.values():
        if ent.runtime == "tier1":
            nodes.append(ent.capability_type)
    topo_mod._DEFAULT_TOPOLOGY = topo_mod.CapabilityTopology(
        nodes=list(dict.fromkeys(nodes)),
        edges=edges,
    )
    return len(edges)


def validate_bootstrap_parity() -> list[str]:
    """Return violations if bootstrap/worker lists diverge from manifest."""
    m = get_manifest()
    violations: list[str] = []
    worker = set(m.worker_agent_types)
    bootstrap = set(m.bootstrap_agent_types)
    if not worker.issubset(bootstrap):
        violations.append(f"worker_not_subset_of_bootstrap:{sorted(worker - bootstrap)}")
    from agents.bootstrap import expected_builtin_agent_types

    expected = tuple(sorted(expected_builtin_agent_types()))
    manifest_bs = tuple(sorted(m.bootstrap_agent_types))
    if expected != manifest_bs:
        violations.append(f"bootstrap_manifest_mismatch:{expected}!={manifest_bs}")

    factories = _load_builtin_factory_keys()
    missing_factory = sorted(set(manifest_bs) - factories)
    if missing_factory:
        violations.append(f"bootstrap_missing_factory:{missing_factory}")

    from kernel.agent_runtime.manifest import validate_manifest_integrity

    violations.extend(validate_manifest_integrity(m))
    return violations


def _load_builtin_factory_keys() -> set[str]:
    from agents.bootstrap import _load_factories

    return set(_load_factories().keys())