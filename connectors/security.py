"""OAuth state and callback validation for connector authorization flows."""

from __future__ import annotations

import time
import uuid
from urllib.parse import urlsplit

import jwt
from jwt import InvalidTokenError

from infra.config.settings import settings


class ConnectorOAuthError(ValueError):
    pass


def _state_secret() -> str:
    secret = str(settings.app_secret_key or settings.jwt_secret or "").strip()
    if not secret:
        raise ConnectorOAuthError("connector OAuth state secret is not configured")
    return secret


def validate_connector_redirect_uri(redirect_uri: str) -> str:
    value = str(redirect_uri or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ConnectorOAuthError("invalid connector redirect URI")
    port = parsed.port
    origin = f"{parsed.scheme.lower()}://{parsed.hostname.lower()}"
    if port is not None:
        origin = f"{origin}:{port}"
    if origin.rstrip("/") not in settings.connector_redirect_origin_list:
        raise ConnectorOAuthError("connector redirect origin is not allowed")
    return value


def issue_connector_oauth_state(
    *,
    user_id: str,
    provider: str,
    redirect_uri: str,
    tenant_id: str = "default",
    workspace_id: str = "default",
    client_state: str = "",
) -> str:
    validated_redirect = validate_connector_redirect_uri(redirect_uri)
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "provider": provider,
            "redirect_uri": validated_redirect,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "client_state": client_state,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + max(60, int(settings.connector_oauth_state_ttl_seconds)),
        },
        _state_secret(),
        algorithm=settings.jwt_algorithm,
    )


def verify_connector_oauth_state(
    state: str,
    *,
    user_id: str,
    provider: str,
    redirect_uri: str,
    tenant_id: str = "default",
    workspace_id: str = "default",
) -> dict:
    validated_redirect = validate_connector_redirect_uri(redirect_uri)
    try:
        payload = jwt.decode(
            state,
            _state_secret(),
            algorithms=[settings.jwt_algorithm],
        )
    except InvalidTokenError as exc:
        raise ConnectorOAuthError("invalid or expired connector OAuth state") from exc
    expected = {
        "sub": user_id,
        "provider": provider,
        "redirect_uri": validated_redirect,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
    }
    if any(str(payload.get(key) or "") != value for key, value in expected.items()):
        raise ConnectorOAuthError("connector OAuth state does not match the callback")
    return payload
