"""Shared chat preflight helper."""

from __future__ import annotations

import pytest

from gateway.api_gateway.chat_preflight import run_chat_preflight, run_chat_preflight_async


def test_run_chat_preflight_allowed():
    md = run_chat_preflight(
        query="hello",
        user_id="u1",
        session_id="s1",
        tenant_md={"tenant_id": "default"},
    )
    assert md.get("tenant_id") == "default"


def test_run_chat_preflight_denied_quota():
    from control_plane.control_plane import get_enterprise_control_plane
    from tenant.tenant_context import resolve_tenant_context

    cp = get_enterprise_control_plane()
    ctx = resolve_tenant_context(tenant_id="pf-deny", org_id="o", workspace_id="w")
    cp.set_quota_limits(ctx, daily_turns=0, daily_cost=0.0)

    from infra.errors import AppException

    with pytest.raises(AppException):
        run_chat_preflight(
            query="hi",
            user_id="u1",
            session_id="s1",
            tenant_md={"tenant_id": "pf-deny", "org_id": "o", "workspace_id": "w"},
        )


@pytest.mark.asyncio
async def test_run_chat_preflight_async_allowed():
    md = await run_chat_preflight_async(
        query="hello",
        user_id="u1",
        session_id="s1",
        tenant_md={"tenant_id": "default"},
    )
    assert md.get("tenant_id") == "default"