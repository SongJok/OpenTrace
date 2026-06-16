"""CapabilityRegistry routing must align with agent_topology_manifest.yaml."""

from __future__ import annotations

from agents.bootstrap import register_builtin_agents
from kernel.agent_runtime.manifest import get_manifest, reload_manifest
from kernel.runtime.capability import capability_registry


def test_registry_resolve_matches_manifest_for_tier1_bootstrap():
    reload_manifest()
    register_builtin_agents(force=True)
    m = get_manifest()
    for agent_type in m.bootstrap_agent_types:
        ent = m.get(agent_type)
        assert ent is not None
        resolved_ct = capability_registry.resolve_capability_type(agent_type)
        assert resolved_ct == ent.capability_type, agent_type
        exec_agent = capability_registry.resolve_execution_agent(ent.capability_type)
        assert capability_registry.has_agent(exec_agent), (
            f"{ent.capability_type} -> {exec_agent}"
        )


def test_web_alias_prefers_web_intelligence_registry():
    reload_manifest()
    register_builtin_agents(force=True)
    cap, reg = get_manifest().resolve_capability_alias("web")
    assert cap == "web_search"
    assert reg == "web_intelligence"
    assert capability_registry.resolve_execution_agent("web") == "web_intelligence"