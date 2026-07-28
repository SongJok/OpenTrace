from __future__ import annotations

import pytest

from gateway.api_gateway.routers.auth import RegisterRequest, get_current_user, login_json
from infra.errors import AppException, ErrorCodes


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, value=None):
        self._value = value

    async def execute(self, _statement):
        return _ScalarResult(self._value)


@pytest.mark.asyncio
async def test_unknown_login_returns_unauthorized_instead_of_internal_error() -> None:
    with pytest.raises(AppException) as raised:
        await login_json(
            RegisterRequest(email="missing@example.com", password="wrong-password"),
            _FakeSession(),  # type: ignore[arg-type]
        )

    assert raised.value.code == ErrorCodes.AUTH_INVALID_CREDENTIALS.code
    assert raised.value.http_status == 401
    assert raised.value.message == "账号或密码错误"


@pytest.mark.asyncio
async def test_invalid_bearer_token_returns_unauthorized() -> None:
    from starlette.requests import Request

    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    with pytest.raises(AppException) as raised:
        await get_current_user(
            request=request,
            token="not-a-jwt",
            db=_FakeSession(),  # type: ignore[arg-type]
        )

    assert raised.value.code == ErrorCodes.AUTH_INVALID_TOKEN.code
    assert raised.value.http_status == 401
    assert raised.value.message == "登录凭证无效或已过期"


@pytest.mark.asyncio
async def test_empty_password_returns_unauthorized_instead_of_crashing() -> None:
    from gateway.api_gateway.routers.auth import _hash
    from infra.storage.models import User

    user = User(
        id="user-empty-password",
        email="dev@example.com",
        hashed_password=_hash("valid-password"),
        display_name="Dev User",
        status="active",
        role="admin",
        is_active=True,
    )
    with pytest.raises(AppException) as raised:
        await login_json(
            RegisterRequest(email=user.email, password=None),
            _FakeSession(user),  # type: ignore[arg-type]
        )

    assert raised.value.code == ErrorCodes.AUTH_INVALID_CREDENTIALS.code
    assert raised.value.http_status == 401
