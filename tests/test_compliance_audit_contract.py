"""Compliance audit store."""

from __future__ import annotations

import pytest

from governance.compliance_audit_store import list_recent_events, record_compliance_event


@pytest.mark.asyncio
async def test_record_compliance_event_memory():
    eid = await record_compliance_event(
        tenant_id="t-audit",
        session_id="s1",
        violations=["soc2_audit_trace_missing"],
        allowed=False,
    )
    assert eid
    recent = list_recent_events("t-audit", limit=5)
    assert recent and recent[0]["event_id"] == eid


@pytest.mark.asyncio
async def test_list_recent_events_from_db_fallback():
    from governance.compliance_audit_store import list_recent_events_from_db

    await record_compliance_event(tenant_id="t-db-fb", allowed=True)
    rows = await list_recent_events_from_db("t-db-fb", limit=5)
    assert rows