"""Email notification sender — admin alerts for new registrations, etc."""

from __future__ import annotations

from infra.observability.logger import get_logger

logger = get_logger(__name__)


async def notify_admin_new_registration(email: str, display_name: str = "") -> None:
    """Send notification to admin about a new user registration awaiting approval."""
    logger.info("New user registration: email=%s display_name=%s", email, display_name)


async def notify_user_approved(email: str, password: str) -> None:
    """Send notification to user that their registration has been approved."""
    logger.info("User approved notification: email=%s", email)
