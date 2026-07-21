"""Behavioral regression tests for the enterprise P0 trust boundaries."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.routing import APIRoute
from starlette.requests import Request

from infra.errors import AppException


def _request(headers: dict[str, str] | None = None) -> Request:
    encoded_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "headers": encoded_headers,
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


def _route_has_dependency(route: APIRoute, dependency) -> bool:
    return any(item.call is dependency for item in route.dependant.dependencies)


def test_unsigned_custom_tenant_scope_is_rejected(monkeypatch):
    from gateway.api_gateway import tenant_middleware as tenant

    monkeypatch.setattr(tenant.settings, "trusted_tenant_header_secret", "tenant-secret")
    monkeypatch.setattr(tenant, "ensure_tenant_registered", lambda *_args, **_kwargs: None)
    with pytest.raises(AppException, match="Untrusted tenant scope"):
        tenant.build_tenant_metadata(
            _request({"X-Tenant-Id": "tenant-a"}),
            user_id="user-a",
        )


def test_signed_tenant_scope_is_user_bound(monkeypatch):
    from gateway.api_gateway import tenant_middleware as tenant

    monkeypatch.setattr(tenant.settings, "trusted_tenant_header_secret", "tenant-secret")
    monkeypatch.setattr(tenant, "ensure_tenant_registered", lambda *_args, **_kwargs: None)
    headers = tenant.sign_tenant_headers(
        user_id="user-a",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        timestamp=int(time.time()),
        secret="tenant-secret",
    )
    metadata = tenant.build_tenant_metadata(_request(headers), user_id="user-a")
    assert metadata["tenant_id"] == "tenant-a"
    assert metadata["workspace_id"] == "workspace-a"

    with pytest.raises(AppException, match="Invalid tenant scope signature"):
        tenant.build_tenant_metadata(_request(headers), user_id="user-b")


def test_default_scope_remains_available_without_proxy_signature(monkeypatch):
    from gateway.api_gateway import tenant_middleware as tenant

    monkeypatch.setattr(tenant, "ensure_tenant_registered", lambda *_args, **_kwargs: None)
    metadata = tenant.build_tenant_metadata(_request(), user_id="user-a")
    assert metadata["tenant_id"] == "default"
    assert metadata["workspace_id"] == "default"


def test_resource_statements_include_owner_tenant_and_workspace():
    from gateway.api_gateway.resource_scope import (
        owned_data_sources_statement,
        scoped_documents_statement,
    )

    scope = {"tenant_id": "tenant-a", "workspace_id": "workspace-a"}
    document_sql = str(
        scoped_documents_statement(
            user_id="user-a",
            tenant_metadata=scope,
            document_id="doc-a",
        )
    )
    source_sql = str(
        owned_data_sources_statement(
            user_id="user-a",
            tenant_metadata=scope,
            data_source_id="source-a",
        )
    )
    assert all(column in document_sql for column in ("owner_id", "tenant_id", "workspace_id"))
    assert all(column in source_sql for column in ("user_id", "tenant_id", "workspace_id"))


def test_control_plane_routes_require_admin_dependency():
    from gateway.api_gateway.routers import admin, analytical_skills, cognitive, rules, skills
    from gateway.api_gateway.routers.admin import get_current_admin_user

    protected_routes = []
    for router in (admin.router, analytical_skills.router, cognitive.router, rules.router):
        protected_routes.extend(route for route in router.routes if isinstance(route, APIRoute))
    protected_routes.extend(
        route
        for route in skills.router.routes
        if isinstance(route, APIRoute) and "/skills/session/" not in route.path
        # Catalog browsing and account-scoped installs are intentionally
        # end-user data-plane APIs. Catalog synchronization and legacy
        # executable-skill administration remain admin-only.
        and route.path
        not in {
            "/skills/catalog",
            "/skills/catalog/install",
            "/skills/installed/me",
            "/skills/installations/{installation_id}",
        }
    )
    assert protected_routes
    missing = [
        route.path
        for route in protected_routes
        if not _route_has_dependency(route, get_current_admin_user)
    ]
    assert missing == []


@pytest.mark.asyncio
async def test_feedback_rejects_session_not_owned_by_user(monkeypatch):
    from evolution.feedback.collector import FeedbackType
    from gateway.api_gateway.routers import feedback

    result = Mock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result
    collect = AsyncMock()
    monkeypatch.setattr(feedback._collector, "collect", collect)

    with pytest.raises(AppException, match="Session not found"):
        await feedback.submit_feedback(
            feedback.FeedbackRequest(
                session_id="session-b",
                query="q",
                response="a",
                feedback_type=FeedbackType.THUMBS_UP,
            ),
            current_user=SimpleNamespace(id="user-a"),
            db=db,
        )
    collect.assert_not_awaited()


def test_managed_environments_force_shadow_learning_and_disable_dynamic_skills():
    from infra.config.settings import Settings

    configured = Settings(
        app_env="staging",
        app_port=14100,
        gateway_port=14100,
        app_secret_key="app-secret",
        jwt_secret="jwt-secret",
        data_secret_key="data-secret",
        kernel_agent_learning_auto_apply=True,
        skills_git_install_enabled=True,
        skills_local_create_enabled=True,
        skills_inprocess_execution_enabled=True,
    )
    assert configured.kernel_agent_learning_auto_apply is False
    assert configured.skills_git_install_enabled is False
    assert configured.skills_local_create_enabled is False
    assert configured.skills_inprocess_execution_enabled is False


def test_managed_rls_requires_tenant_signing_secret():
    from infra.config.settings import Settings

    with pytest.raises(ValueError, match="TRUSTED_TENANT_HEADER_SECRET"):
        Settings(
            app_env="production",
            app_port=14100,
            gateway_port=14100,
            app_secret_key="app-secret",
            jwt_secret="jwt-secret",
            data_secret_key="data-secret",
            enterprise_tenant_rls_enabled=True,
            trusted_tenant_header_secret="",
        )


def test_cors_rejects_wildcard_origin_with_credentials():
    from infra.config.settings import Settings

    with pytest.raises(ValueError, match="must not contain"):
        Settings(cors_allowed_origins="*", app_port=14100, gateway_port=14100)


def test_stream_errors_are_redacted_outside_development_debug(monkeypatch):
    from pathlib import Path

    worker = (Path(__file__).resolve().parents[1] / "infra/responses/worker.py").read_text()
    assert 'response.error_message = "响应执行失败，请稍后重试。"' in worker
    assert 'event_type="response.failed"' in worker
    assert '"status": "failed"' in worker
    assert '"code": response.error_code' in worker
    assert '"message": response.error_message' in worker


@pytest.mark.parametrize(
    "sql",
    [
        "WITH changed AS (DELETE FROM users RETURNING *) SELECT * FROM changed",
        "WITH changed AS (UPDATE users SET name = 'x' RETURNING *) SELECT * FROM changed",
        "SELECT pg_sleep(10)",
        "SELECT * FROM read_csv_auto('/tmp/private.csv')",
        "SELECT * FROM users FOR UPDATE",
        "SELECT 1; SELECT 2",
    ],
)
def test_sql_ast_firewall_rejects_mutation_and_side_effects(sql):
    from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator

    with pytest.raises(SQLValidationError):
        SQLValidator(default_limit=100, max_limit=500).validate(sql)


def test_sql_ast_firewall_caps_top_level_limit():
    from kernel.data_cognition.sql_validator import SQLValidator

    safe_sql = SQLValidator(default_limit=100, max_limit=500).validate(
        "SELECT * FROM events LIMIT 100000"
    )
    assert "LIMIT 500" in safe_sql


def test_sql_executor_configures_read_only_transaction_and_limits():
    from execution.data.sql_executor import SQLExecutor

    executor = SQLExecutor(max_rows=25, timeout_ms=1200)
    postgres_setup = executor._read_only_setup_statements("postgresql+asyncpg://db")
    mysql_setup = executor._read_only_setup_statements("mysql+asyncmy://db")
    assert "SET TRANSACTION READ ONLY" in postgres_setup
    assert any("statement_timeout" in statement for statement in postgres_setup)
    assert "SET TRANSACTION READ ONLY" in mysql_setup
    assert "LIMIT 25" in executor._validated_sql("SELECT * FROM events")


def test_dynamic_skill_install_and_create_are_disabled_by_default(monkeypatch):
    from infra.config.settings import settings
    from skills.store.marketplace import SkillMarketplace

    monkeypatch.setattr(settings, "skills_git_install_enabled", False)
    monkeypatch.setattr(settings, "skills_local_create_enabled", False)
    marketplace = SkillMarketplace()
    with pytest.raises(PermissionError, match="installation is disabled"):
        marketplace.install_from_git("https://example.invalid/skill.git")
    with pytest.raises(PermissionError, match="creation is disabled"):
        marketplace.create_local("blocked", "1.0.0", "main.py", "print('blocked')")


def test_data_source_tenant_migration_is_chained_and_idempotent():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260710_data_sources_tenant_workspace.py"
    )
    source = path.read_text(encoding="utf-8")
    assert 'down_revision = "20260613_documents_tenant"' in source
    assert 'if "tenant_id" not in columns' in source
    assert 'if "workspace_id" not in columns' in source
    assert "ix_data_sources_scope_owner" in source
