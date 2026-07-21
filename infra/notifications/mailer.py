"""SMTP email notifications for the registration approval flow."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from email.message import EmailMessage
from html import escape
from typing import Any

import aiosmtplib

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()


def _smtp_tls_options() -> tuple[bool, bool]:
    use_tls = settings.smtp_use_tls
    start_tls = settings.smtp_start_tls
    if use_tls is None:
        use_tls = settings.smtp_port == 465
    if start_tls is None:
        start_tls = settings.smtp_port == 587
    if use_tls and start_tls:
        raise RuntimeError("SMTP_USE_TLS and SMTP_START_TLS cannot both be enabled")
    return use_tls, start_tls


def _require_smtp_config() -> tuple[str, str]:
    host = settings.smtp_host.strip()
    sender = (settings.smtp_from or settings.smtp_user).strip()
    username = settings.smtp_user.strip()
    password = settings.smtp_pass.strip()

    missing = []
    if not host:
        missing.append("SMTP_HOST")
    if not sender:
        missing.append("SMTP_FROM")
    if bool(username) != bool(password):
        missing.append("SMTP_USER/SMTP_PASS must be configured together")
    if missing:
        raise RuntimeError(f"SMTP is not configured: {', '.join(missing)}")
    return host, sender


async def _send_email(
    *,
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    host, sender = _require_smtp_config()
    use_tls, start_tls = _smtp_tls_options()

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    await aiosmtplib.send(
        message,
        hostname=host,
        port=settings.smtp_port,
        username=settings.smtp_user.strip() or None,
        password=settings.smtp_pass or None,
        timeout=settings.smtp_timeout_seconds,
        use_tls=use_tls,
        start_tls=start_tls,
    )
    logger.info("Email notification sent", recipient=recipient, subject=subject)


def schedule_email_notification(
    notification: Coroutine[Any, Any, None],
    *,
    kind: str,
    recipient: str,
) -> None:
    """Keep a background email task alive and observe delivery failures."""
    task = asyncio.create_task(notification)
    _background_tasks.add(task)

    def _task_done(completed: asyncio.Task[None]) -> None:
        _background_tasks.discard(completed)
        if completed.cancelled():
            logger.warning("Email notification cancelled", kind=kind, recipient=recipient)
            return
        error = completed.exception()
        if error is not None:
            logger.error(
                "Email notification failed",
                kind=kind,
                recipient=recipient,
                error=str(error),
            )

    task.add_done_callback(_task_done)


async def notify_admin_new_registration(email: str, display_name: str = "") -> None:
    """Send notification to admin about a new user registration awaiting approval."""
    safe_email = escape(email)
    safe_name = escape(display_name or "未填写")
    await _send_email(
        recipient=settings.admin_email.strip(),
        subject=f"[{settings.app_name}] 新用户注册待审核",
        text_body=(
            "有新的用户注册申请等待审核。\n\n"
            f"邮箱：{email}\n"
            f"显示名称：{display_name or '未填写'}\n\n"
            "请登录管理后台处理。"
        ),
        html_body=(
            "<p>有新的用户注册申请等待审核。</p>"
            f"<p><strong>邮箱：</strong>{safe_email}<br>"
            f"<strong>显示名称：</strong>{safe_name}</p>"
            "<p>请登录管理后台处理。</p>"
        ),
    )


async def notify_user_approved(email: str, password: str) -> None:
    """Send notification to user that their registration has been approved."""
    safe_email = escape(email)
    safe_password = escape(password)
    await _send_email(
        recipient=email,
        subject=f"[{settings.app_name}] 注册审核已通过",
        text_body=(
            "您的注册申请已通过审核。\n\n"
            f"登录邮箱：{email}\n"
            f"临时密码：{password}\n\n"
            "请登录系统后妥善保管您的账号信息。"
        ),
        html_body=(
            "<p>您的注册申请已通过审核。</p>"
            f"<p><strong>登录邮箱：</strong>{safe_email}<br>"
            f"<strong>临时密码：</strong><code>{safe_password}</code></p>"
            "<p>请登录系统后妥善保管您的账号信息。</p>"
        ),
    )
