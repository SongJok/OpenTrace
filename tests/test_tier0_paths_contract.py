"""Tier-0 chat fast paths — manifest aliases and governance envelope."""

from __future__ import annotations

from kernel.agent_runtime.manifest import get_manifest, reload_manifest


def test_manifest_resolve_web_aliases():
    reload_manifest()
    m = get_manifest()
    cap, reg = m.resolve_capability_alias("web")
    assert cap == "web_search"
    assert reg == "web_intelligence"
    cap, reg = m.resolve_capability_alias("web.search")
    assert cap == "web_search"
    assert reg in {"web_intelligence", "web"}
    cap2, reg2 = m.resolve_capability_alias("web_intelligence")
    assert cap2 == "web_search"
    assert reg2 == "web_intelligence"


def test_manifest_resolve_data_query():
    reload_manifest()
    m = get_manifest()
    cap, reg = m.resolve_capability_alias("data_query")
    assert cap == "data_query"
    assert reg == "data"


def test_tier0_governance_envelope_fields():
    from gateway.api_gateway.tier0_paths import tier0_governance_envelope

    reload_manifest()
    meta = tier0_governance_envelope(
        route="tier0_data_query",
        capability_type="data_query",
        registry_agent="data",
        request_id="req-1",
        session_id="sess-1",
    )
    assert meta["tier0_fast_path"] is True
    assert meta["capability_type"] == "data_query"
    assert meta["registry_agent"] == "data"
    assert meta["manifest_version"].startswith("3.")
    assert "semantic_observability" in meta


def test_is_sql_retrieval_intent():
    from gateway.api_gateway.tier0_paths import is_sql_retrieval_intent

    assert is_sql_retrieval_intent("刚才的SQL是什么")
    assert not is_sql_retrieval_intent("帮我统计订单数")