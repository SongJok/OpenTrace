from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request

from connectors.sdk.protocol import CredentialRef


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/connectors",
            "raw_path": b"/connectors",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


def test_connector_oauth_state_is_signed_scoped_and_expiring(monkeypatch):
    from connectors.security import issue_connector_oauth_state, verify_connector_oauth_state
    from infra.config.settings import settings

    monkeypatch.setattr(settings, "app_secret_key", "connector-state-secret")
    monkeypatch.setattr(
        settings,
        "connector_allowed_redirect_origins",
        "https://app.example.com",
    )
    state = issue_connector_oauth_state(
        user_id="u1",
        provider="github",
        redirect_uri="https://app.example.com/oauth/callback",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        client_state="client-nonce",
    )
    payload = verify_connector_oauth_state(
        state,
        user_id="u1",
        provider="github",
        redirect_uri="https://app.example.com/oauth/callback",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
    )
    assert payload["client_state"] == "client-nonce"
    assert payload["exp"] > payload["iat"]


def test_connector_oauth_state_rejects_cross_tenant_callback(monkeypatch):
    from connectors.security import (
        ConnectorOAuthError,
        issue_connector_oauth_state,
        verify_connector_oauth_state,
    )
    from infra.config.settings import settings

    monkeypatch.setattr(settings, "app_secret_key", "connector-state-secret")
    monkeypatch.setattr(
        settings,
        "connector_allowed_redirect_origins",
        "https://app.example.com",
    )
    state = issue_connector_oauth_state(
        user_id="u1",
        provider="github",
        redirect_uri="https://app.example.com/oauth/callback",
        tenant_id="tenant-a",
    )
    with pytest.raises(ConnectorOAuthError, match="does not match"):
        verify_connector_oauth_state(
            state,
            user_id="u1",
            provider="github",
            redirect_uri="https://app.example.com/oauth/callback",
            tenant_id="tenant-b",
        )


def test_connector_redirect_origin_is_allowlisted(monkeypatch):
    from connectors.security import ConnectorOAuthError, validate_connector_redirect_uri
    from infra.config.settings import settings

    monkeypatch.setattr(
        settings,
        "connector_allowed_redirect_origins",
        "https://app.example.com",
    )
    with pytest.raises(ConnectorOAuthError, match="not allowed"):
        validate_connector_redirect_uri("https://attacker.example.net/callback")


def test_connector_credential_encryption_round_trip(monkeypatch):
    from infra.config.settings import get_settings
    from infra.security.connector_credentials import (
        decrypt_connector_credential,
        encrypt_connector_credential,
    )

    monkeypatch.setattr(get_settings(), "data_secret_key", "connector-data-secret")
    credential = CredentialRef(
        provider="github",
        account_id="acct-1",
        access_token="top-secret-token",
        refresh_token="refresh-secret",
        expires_at=123456,
        metadata={"scope": "repo"},
    )
    encrypted = encrypt_connector_credential(credential)
    assert "top-secret-token" not in encrypted
    restored = decrypt_connector_credential(encrypted)
    assert restored == credential


@pytest.mark.asyncio
async def test_connector_credential_lookup_is_tenant_scoped(monkeypatch):
    from gateway.api_gateway.routers import connectors
    from infra.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "data_secret_key", "connector-data-secret")
    credential = CredentialRef(provider="github", account_id="acct", access_token="token")
    encrypted = connectors.encrypt_connector_credential(credential)
    row = SimpleNamespace(credential_encrypted=encrypted)
    result = Mock()
    result.scalar_one_or_none.return_value = row
    db = AsyncMock()
    db.execute.return_value = result

    restored = await connectors._get_user_credential(
        db,
        _request(),
        SimpleNamespace(id="u1"),
        "github",
    )
    statement = db.execute.await_args.args[0]
    sql = str(statement)
    assert all(field in sql for field in ("user_id", "tenant_id", "workspace_id", "provider"))
    assert restored.access_token == "token"


def test_connector_credential_migration_is_chained():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260712_connector_credentials.py"
    source = path.read_text(encoding="utf-8")
    assert 'down_revision = "20260711_chat_session_skills"' in source
    assert "credential_encrypted" in source
    assert "uq_connector_credential_scope_provider" in source
