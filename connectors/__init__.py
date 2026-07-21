from connectors.registry import connector_registry
from connectors.builtin.github_connector import GitHubConnector


def register_builtin_connectors() -> None:
    try:
        connector_registry.get("github")
        return
    except KeyError:
        connector_registry.register("github", GitHubConnector())
