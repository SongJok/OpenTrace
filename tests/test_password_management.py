from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from gateway.api_gateway.routers.admin import (
    ResetPasswordRequest,
    reset_user_password,
)
from gateway.api_gateway.routers.auth import (
    ChangePasswordRequest,
    _hash,
    _verify,
    change_password,
)
from infra.errors import AppException, ErrorCodes


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


def _user(*, password: str, status: str = "active") -> SimpleNamespace:
    return SimpleNamespace(
        id="user-1",
        email="user@example.com",
        hashed_password=_hash(password),
        status=status,
    )


def test_password_requests_enforce_minimum_length_and_bcrypt_byte_limit() -> None:
    with pytest.raises(ValidationError):
        ChangePasswordRequest(old_password="old-password", new_password="short")
    with pytest.raises(ValidationError):
        ResetPasswordRequest(new_password="密" * 25)


@pytest.mark.asyncio
async def test_user_can_change_password_with_correct_old_password() -> None:
    user = _user(password="old-password")
    db = SimpleNamespace(commit=AsyncMock())

    result = await change_password(
        ChangePasswordRequest(old_password="old-password", new_password="new-password"),
        current_user=user,
        db=db,
    )

    assert result == {"message": "密码修改成功"}
    assert _verify("new-password", user.hashed_password)
    assert not _verify("old-password", user.hashed_password)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_change_password_rejects_wrong_old_password_without_writing() -> None:
    user = _user(password="old-password")
    original_hash = user.hashed_password
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(AppException) as exc_info:
        await change_password(
            ChangePasswordRequest(old_password="wrong-password", new_password="new-password"),
            current_user=user,
            db=db,
        )

    assert exc_info.value.code == ErrorCodes.PARAM_INVALID.code
    assert exc_info.value.message == "原密码不正确"
    assert user.hashed_password == original_hash
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_can_reset_an_active_user_password() -> None:
    target = _user(password="old-password")
    admin = SimpleNamespace(id="admin-1", email="admin@example.com")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(target)),
        commit=AsyncMock(),
    )

    result = await reset_user_password(
        target.id,
        ResetPasswordRequest(new_password="reset-password"),
        current_user=admin,
        db=db,
    )

    assert result == {"message": "用户密码已重置"}
    assert _verify("reset-password", target.hashed_password)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_cannot_reset_a_pending_user_password() -> None:
    target = _user(password="old-password", status="pending")
    original_hash = target.hashed_password
    admin = SimpleNamespace(id="admin-1", email="admin@example.com")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(target)),
        commit=AsyncMock(),
    )

    with pytest.raises(AppException) as exc_info:
        await reset_user_password(
            target.id,
            ResetPasswordRequest(new_password="reset-password"),
            current_user=admin,
            db=db,
        )

    assert exc_info.value.code == ErrorCodes.PARAM_INVALID.code
    assert target.hashed_password == original_hash
    db.commit.assert_not_awaited()
