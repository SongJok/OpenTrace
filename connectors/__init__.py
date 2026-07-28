from __future__ import annotations

from connectors.builtin.confluence_connector import ConfluenceConnector
from connectors.builtin.github_connector import GitHubConnector
from connectors.builtin.slack_connector import SlackConnector
from connectors.registry import connector_registry
from infra.config.settings import settings

_registered = False


def register_builtin_connectors() -> None:
    global _registered
    if _registered:
        return
    connector_registry.register(
        "github",
        GitHubConnector(
            client_id=settings.github_connector_client_id,
            client_secret=settings.github_connector_client_secret,
        ),
    )
    connector_registry.register(
        "slack",
        SlackConnector(
            client_id=settings.slack_connector_client_id,
            client_secret=settings.slack_connector_client_secret,
        ),
    )
    connector_registry.register(
        "confluence",
        ConfluenceConnector(
            client_id=settings.confluence_connector_client_id,
            client_secret=settings.confluence_connector_client_secret,
        ),
    )
    _registered = True
