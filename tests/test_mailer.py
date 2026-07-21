from __future__ import annotations

from email.message import EmailMessage
from unittest.mock import AsyncMock

import pytest

from infra.config.settings import settings
from infra.notifications import mailer


@pytest.fixture
def smtp_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_name", "OpenTrace")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 465)
    monkeypatch.setattr(settings, "smtp_user", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_pass", "app-password")
    monkeypatch.setattr(settings, "smtp_from", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", None)
    monkeypatch.setattr(settings, "smtp_start_tls", None)
    monkeypatch.setattr(settings, "smtp_timeout_seconds", 15.0)
    monkeypatch.setattr(settings, "admin_email", "admin@example.com")


@pytest.mark.asyncio
async def test_approval_notification_sends_temp_password(
    monkeypatch: pytest.MonkeyPatch,
    smtp_settings: None,
) -> None:
    send = AsyncMock(return_value=({}, "ok"))
    monkeypatch.setattr(mailer.aiosmtplib, "send", send)

    await mailer.notify_user_approved("new.user@example.com", "Tmp-123456")

    send.assert_awaited_once()
    message = send.await_args.args[0]
    assert isinstance(message, EmailMessage)
    assert message["To"] == "new.user@example.com"
    assert "审核已通过" in str(message["Subject"])
    assert "Tmp-123456" in message.get_body(preferencelist=("plain",)).get_content()
    assert send.await_args.kwargs["use_tls"] is True
    assert send.await_args.kwargs["start_tls"] is False


@pytest.mark.asyncio
async def test_registration_notification_goes_to_admin_and_escapes_html(
    monkeypatch: pytest.MonkeyPatch,
    smtp_settings: None,
) -> None:
    send = AsyncMock(return_value=({}, "ok"))
    monkeypatch.setattr(mailer.aiosmtplib, "send", send)

    await mailer.notify_admin_new_registration(
        "new.user@example.com",
        "<script>alert(1)</script>",
    )

    message = send.await_args.args[0]
    assert message["To"] == "admin@example.com"
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.asyncio
async def test_port_587_defaults_to_starttls(
    monkeypatch: pytest.MonkeyPatch,
    smtp_settings: None,
) -> None:
    monkeypatch.setattr(settings, "smtp_port", 587)
    send = AsyncMock(return_value=({}, "ok"))
    monkeypatch.setattr(mailer.aiosmtplib, "send", send)

    await mailer.notify_user_approved("new.user@example.com", "Tmp-123456")

    assert send.await_args.kwargs["use_tls"] is False
    assert send.await_args.kwargs["start_tls"] is True


@pytest.mark.asyncio
async def test_incomplete_auth_configuration_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
    smtp_settings: None,
) -> None:
    monkeypatch.setattr(settings, "smtp_pass", "")

    with pytest.raises(RuntimeError, match="SMTP_USER/SMTP_PASS"):
        await mailer.notify_user_approved("new.user@example.com", "Tmp-123456")
