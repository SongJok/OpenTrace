"""Enterprise admin router wiring."""

from __future__ import annotations

from gateway.api_gateway.routers import enterprise_admin


def test_enterprise_admin_routes_registered():
    paths = [getattr(r, "path", "") for r in enterprise_admin.router.routes]
    assert any("marketplace" in p for p in paths)
    assert any("compliance" in p for p in paths)
    assert any("quota" in p for p in paths)