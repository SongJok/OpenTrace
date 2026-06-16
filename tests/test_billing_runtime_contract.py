"""Billing runtime cost alignment with finalize_turn metadata."""

from __future__ import annotations

from tenant.billing_runtime import (
    apply_billing_to_metadata,
    estimate_cost_from_tokens,
    resolve_turn_cost,
)


def test_estimate_cost_from_tokens():
    c = estimate_cost_from_tokens(prompt_tokens=1_000_000, completion_tokens=0, extra_cost=0.0)
    assert c > 0


def test_resolve_turn_cost_prefers_explicit():
    assert resolve_turn_cost({"estimated_cost": 1.25}) == 1.25


def test_apply_billing_to_metadata_writes_attribution():
    md = apply_billing_to_metadata(
        {"prompt_tokens": 1000, "completion_tokens": 500, "capability_type": "rag"},
        capability_type="document_retrieval",
        goal_id="g1",
    )
    assert "billing_attribution" in md
    assert md["estimated_cost"] == md["turn_cost"]
    assert md["billing_attribution"]["goal_id"] == "g1"


def test_record_turn_billing_skips_ledger_when_persist_disabled(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from tenant.billing_runtime import record_turn_billing
    from tenant.tenant_context import TenantContext

    ctx = TenantContext(tenant_id="t1", org_id="", workspace_id="", goal_id="g1")
    with patch("tenant.billing_store.persist_ledger_entry", new_callable=AsyncMock) as pl:
        record_turn_billing(
            ctx,
            metadata={"estimated_cost": 0.5, "prompt_tokens": 10, "completion_tokens": 5},
            capability_type="rag",
            session_id="s1",
        )
        pl.assert_not_called()


def test_record_turn_billing_persists_when_flag_enabled(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from infra.config import settings as settings_mod
    from tenant.billing_runtime import record_turn_billing
    from tenant.tenant_context import TenantContext

    monkeypatch.setattr(settings_mod.settings, "enterprise_billing_persist_enabled", True)

    ctx = TenantContext(tenant_id="t1", org_id="", workspace_id="", goal_id="g1")
    with patch("tenant.billing_store.persist_ledger_entry", new_callable=AsyncMock) as pl:
        pl.return_value = True
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            record_turn_billing(
                ctx,
                metadata={"estimated_cost": 0.5, "prompt_tokens": 10, "completion_tokens": 5},
                capability_type="rag",
                session_id="s1",
            )
        assert pl.called