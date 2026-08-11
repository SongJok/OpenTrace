"""Load and query Agent Topology Manifest (SSOT for agents / tier-2 nodes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_MANIFEST_PATH = Path(__file__).resolve().parent / "agent_topology_manifest.yaml"


@dataclass(frozen=True)
class ManifestContract:
    risk_tier: str = "low"
    max_latency_ms: int = 60_000
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManifestEntry:
    key: str
    runtime: str  # tier1 | tier2
    owner_runtime: str
    capability_type: str
    registry_name: str = ""
    bootstrap: bool = False
    worker: bool = False
    bus_eligible: bool = False
    node_role: str = ""
    contract: ManifestContract = field(default_factory=ManifestContract)
    topology: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass
class AgentTopologyManifest:
    version: str
    entries: dict[str, ManifestEntry]
    topology_edges: list[tuple[str, str]]
    bootstrap_agent_types: tuple[str, ...]
    worker_agent_types: tuple[str, ...]

    def tier1_registry_names(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                e.registry_name or e.key
                for e in self.entries.values()
                if e.runtime == "tier1" and e.bootstrap
            )
        )

    def tier2_node_keys(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, e in self.entries.items() if e.runtime == "tier2"))

    def get(self, key: str) -> ManifestEntry | None:
        return self.entries.get((key or "").lower())

    def capability_type_for_agent(self, agent_type: str) -> str:
        ent = self.get(agent_type)
        if ent:
            return ent.capability_type
        return agent_type

    def owner_runtime_for(self, agent_type: str) -> str:
        ent = self.get(agent_type)
        return ent.owner_runtime if ent else "tier1_executive"

    def is_tier2_node(self, agent_type: str) -> bool:
        ent = self.get(agent_type)
        return bool(ent and ent.runtime == "tier2")

    def registry_name_for_capability_type(self, capability_type: str) -> str:
        """Map canonical capability_type (e.g. web_search) to tier-1 registry agent name."""
        ct = (capability_type or "").strip().lower()
        for ent in self.entries.values():
            if ent.runtime != "tier1":
                continue
            if ent.capability_type.lower() == ct:
                return ent.registry_name or ent.key
        return ct.replace(".", "_")

    def resolve_capability_alias(self, name: str) -> tuple[str, str]:
        """Resolve planner/dispatch aliases to (capability_type, registry_name).

        Accepts: web, web.search, web_search, web_intelligence, data, data_query, etc.
        """
        raw = (name or "").strip().lower()
        if not raw:
            return ("", "")

        if raw in {"web", "web.search", "web_search", "web_intel"}:
            wi = self.get("web_intelligence")
            if wi:
                return (wi.capability_type, wi.registry_name or wi.key)
            web = self.get("web")
            if web:
                return (web.capability_type, web.registry_name or web.key)

        ent = self.get(raw)
        if ent and ent.runtime == "tier1":
            if ent.key == "web":
                pref = self.preferred_web_registry_name()
                pref_ent = self.get(pref)
                if pref_ent:
                    return (pref_ent.capability_type, pref_ent.registry_name or pref_ent.key)
            return (ent.capability_type, ent.registry_name or ent.key)

        normalized = raw.replace("_", ".")
        for ent in self.entries.values():
            if ent.runtime != "tier1":
                continue
            cap = ent.capability_type.lower()
            reg = (ent.registry_name or ent.key).lower()
            if normalized == cap or normalized == reg or raw == cap or raw == reg:
                return (ent.capability_type, ent.registry_name or ent.key)

        if raw in {"web", "web.search"}:
            wi = self.get("web_intelligence")
            web = self.get("web")
            if wi:
                return (wi.capability_type, wi.registry_name or wi.key)
            if web:
                return (web.capability_type, web.registry_name or web.key)
        if raw in {"data_query", "data_intelligence"}:
            data = self.get("data")
            if data:
                return (data.capability_type, data.registry_name or data.key)

        return (raw, raw.replace(".", "_"))

    def preferred_web_registry_name(self) -> str:
        """Keep the legacy web alias canonical without enabling web execution."""
        wi = self.get("web_intelligence")
        if wi:
            return wi.registry_name or wi.key
        web = self.get("web")
        return (web.registry_name or web.key) if web else "web"

    def bus_eligible_agent_types(self) -> tuple[str, ...]:
        """Tier-1 agents that may receive Redis bus tasks (manifest bus_eligible)."""
        return tuple(
            sorted(
                (e.registry_name or e.key)
                for e in self.entries.values()
                if e.runtime == "tier1" and e.worker and e.bus_eligible
            )
        )

    def assert_bus_routing(self, agent_type: str) -> None:
        """Raise if dispatch attempts to publish a bus task for a non-eligible agent."""
        at = (agent_type or "").strip().lower()
        ent = self.get(at)
        if ent and ent.runtime == "tier1" and ent.worker and not ent.bus_eligible:
            raise ValueError(f"agent_not_bus_eligible:{at}")


def _parse_contract(raw: dict[str, Any] | None) -> ManifestContract:
    raw = raw or {}
    deps = raw.get("dependencies") or []
    return ManifestContract(
        risk_tier=str(raw.get("risk_tier", "low")),
        max_latency_ms=int(raw.get("max_latency_ms", 60_000)),
        dependencies=tuple(str(d) for d in deps),
    )


def load_manifest(path: Path | None = None) -> AgentTopologyManifest:
    p = path or _MANIFEST_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries_raw = data.get("entries") or {}
    entries: dict[str, ManifestEntry] = {}
    for key, raw in entries_raw.items():
        if not isinstance(raw, dict):
            continue
        k = key.lower()
        entries[k] = ManifestEntry(
            key=k,
            runtime=str(raw.get("runtime", "tier1")),
            owner_runtime=str(raw.get("owner_runtime", "tier1_executive")),
            capability_type=str(raw.get("capability_type", k)),
            registry_name=str(raw.get("registry_name", k)),
            bootstrap=bool(raw.get("bootstrap", False)),
            worker=bool(raw.get("worker", False)),
            bus_eligible=bool(raw.get("bus_eligible", False)),
            node_role=str(raw.get("node_role", "")),
            contract=_parse_contract(raw.get("contract")),
            topology=dict(raw.get("topology") or {}),
            notes=str(raw.get("notes", "")),
        )
    edges: list[tuple[str, str]] = []
    for edge in data.get("topology_edges") or []:
        if isinstance(edge, dict):
            edges.append((str(edge.get("from", "")), str(edge.get("to", ""))))
    bootstrap = tuple(str(x).lower() for x in (data.get("bootstrap_agent_types") or []))
    worker = tuple(str(x).lower() for x in (data.get("worker_agent_types") or []))
    return AgentTopologyManifest(
        version=str(data.get("version", "0")),
        entries=entries,
        topology_edges=edges,
        bootstrap_agent_types=bootstrap,
        worker_agent_types=worker,
    )


def reload_manifest() -> AgentTopologyManifest:
    get_manifest.cache_clear()
    return get_manifest()


@lru_cache(maxsize=1)
def get_manifest() -> AgentTopologyManifest:
    return load_manifest()


def _derived_bootstrap_types(entries: dict[str, ManifestEntry]) -> tuple[str, ...]:
    return tuple(
        sorted(
            (e.registry_name or e.key)
            for e in entries.values()
            if e.runtime == "tier1" and e.bootstrap
        )
    )


def _derived_worker_types(entries: dict[str, ManifestEntry]) -> tuple[str, ...]:
    return tuple(
        sorted(
            (e.registry_name or e.key)
            for e in entries.values()
            if e.runtime == "tier1" and e.worker
        )
    )


def validate_manifest_integrity(manifest: AgentTopologyManifest | None = None) -> list[str]:
    """Ensure YAML lists match entry flags and tier-1 invariants."""
    m = manifest or get_manifest()
    violations: list[str] = []

    derived_bs = set(_derived_bootstrap_types(m.entries))
    derived_worker = set(_derived_worker_types(m.entries))
    yaml_bs = set(m.bootstrap_agent_types)
    yaml_worker = set(m.worker_agent_types)

    if derived_bs != yaml_bs:
        violations.append(
            f"bootstrap_list_mismatch:yaml={sorted(yaml_bs)} entries={sorted(derived_bs)}"
        )
    if derived_worker != yaml_worker:
        violations.append(
            f"worker_list_mismatch:yaml={sorted(yaml_worker)} entries={sorted(derived_worker)}"
        )
    if not yaml_worker.issubset(yaml_bs):
        violations.append(f"worker_not_subset_of_bootstrap:{sorted(yaml_worker - yaml_bs)}")

    for key in yaml_bs:
        ent = m.get(key)
        if not ent or ent.runtime != "tier1":
            violations.append(f"bootstrap_unknown_or_not_tier1:{key}")
        elif not ent.bootstrap:
            violations.append(f"bootstrap_flag_false:{key}")

    for key in yaml_worker:
        if not m.get(key):
            violations.append(f"worker_unknown:{key}")

    for ent in m.entries.values():
        if ent.runtime != "tier1":
            continue
        if ent.bus_eligible and not ent.worker:
            violations.append(f"bus_eligible_requires_worker:{ent.key}")
        if ent.worker and ent.bus_eligible and not ent.bootstrap:
            violations.append(f"bus_worker_requires_bootstrap:{ent.key}")

    return violations
