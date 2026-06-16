"""Web capability naming — manifest SSOT for planner/dispatch/registry."""

from __future__ import annotations

from kernel.agent_runtime.manifest import get_manifest, reload_manifest


def test_manifest_web_aliases_canonical():
    reload_manifest()
    m = get_manifest()
    for alias in ("web", "web.search", "web_search", "web_intel", "web_intelligence"):
        cap, reg = m.resolve_capability_alias(alias)
        assert cap == "web_search", f"alias={alias} cap={cap}"
        assert reg == "web_intelligence", f"alias={alias} reg={reg}"


def test_registry_resolve_capability_type_web():
    reload_manifest()
    from kernel.runtime.capability import capability_registry

    for raw in ("web", "web.search", "web_intelligence", "web_search"):
        resolved = capability_registry.resolve_capability_type(raw)
        assert resolved == "web_search", f"raw={raw} got={resolved}"


def test_capability_adapter_web_source_prefers_web_search():
    from kernel.capability_intelligence.adapter import CapabilityAdapter
    from kernel.capability_intelligence.profile import CapabilityProfile

    profiles = [
        CapabilityProfile(
            capability_type="web_search",
            description="Web search",
            agent_type="web_intelligence",
            reliability=0.9,
        ),
        CapabilityProfile(
            capability_type="web.browse",
            description="Browse",
            agent_type="web",
            reliability=0.7,
        ),
    ]
    best = CapabilityAdapter.find_best_capability("web", "需要联网搜索", profiles)
    assert best == "web_search"