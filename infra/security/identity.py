"""本地 JWT 与企业 OIDC 的统一验证边界。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt
from jwt import InvalidTokenError, PyJWKClient

from infra.config.settings import settings


def is_enterprise_admin(user: Any) -> bool:
    """统一管理员语义，避免 role=admin 与 superuser 在业务面产生权限分叉。"""

    return bool(getattr(user, "is_superuser", False) or getattr(user, "role", "") == "admin")


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, lifespan=300)


def decode_access_token(token: str) -> dict[str, Any]:
    """按受信 issuer 选择验证器；绝不根据未验证 claim 放宽算法。"""
    if settings.identity_oidc_enabled:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except InvalidTokenError:
            unverified = {}
        if str(unverified.get("iss") or "") == settings.identity_oidc_issuer:
            signing_key = _jwks_client(settings.identity_oidc_jwks_url).get_signing_key_from_jwt(
                token
            )
            algorithms = [
                item.strip()
                for item in settings.identity_oidc_algorithms.split(",")
                if item.strip()
            ]
            return dict(
                jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=algorithms,
                    audience=settings.identity_oidc_audience,
                    issuer=settings.identity_oidc_issuer,
                    options={"require": ["exp", "iat", "iss", "sub"]},
                )
            )
    return dict(
        jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    )
