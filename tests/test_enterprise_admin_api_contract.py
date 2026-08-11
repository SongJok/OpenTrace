"""企业目录与企业大脑管理员路由边界。"""

from __future__ import annotations

from gateway.api_gateway.routers import enterprise_admin


def test_enterprise_admin_routes_are_limited_to_retained_modules():
    paths = [getattr(r, "path", "") for r in enterprise_admin.router.routes]
    assert any("/directory/" in path for path in paths)
    assert any("/cognition/" in path for path in paths)
    assert not any("marketplace" in path for path in paths)
    assert not any("compliance" in path for path in paths)
    assert not any("quota" in path for path in paths)
