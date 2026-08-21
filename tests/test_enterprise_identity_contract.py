from __future__ import annotations

import jwt

from gateway.api_gateway.routers import auth
from infra.security.identity import decode_access_token

TEST_JWT_SECRET = "identity-contract-test-secret-32bytes"


def test_local_token_contains_revocation_and_version_claims(monkeypatch):
    monkeypatch.setattr(auth.settings, "jwt_secret", TEST_JWT_SECRET)
    token = auth._create_token("u1", "u@example.com", 3)
    payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=[auth.settings.jwt_algorithm])
    assert payload["jti"]
    assert payload["ver"] == 3
    assert payload["iat"] < payload["exp"]


def test_local_identity_decoder_rejects_missing_jti(monkeypatch):
    monkeypatch.setattr(auth.settings, "jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr(auth.settings, "identity_oidc_enabled", False)
    token = jwt.encode(
        {"sub": "u1", "iat": 1, "exp": 9999999999},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    try:
        decode_access_token(token)
    except jwt.InvalidTokenError:
        pass
    else:
        raise AssertionError("missing jti token should be rejected")
