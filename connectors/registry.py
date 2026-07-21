from __future__ import annotations

from typing import Any

from connectors.sdk.protocol import BaseConnector


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, name: str, connector: BaseConnector) -> None:
        self._connectors[name] = connector

    def get(self, name: str) -> BaseConnector:
        if name not in self._connectors:
            raise KeyError(f"connector not found: {name}")
        return self._connectors[name]

    def list(self) -> list[dict[str, Any]]:
        return [{"name": k} for k in sorted(self._connectors.keys())]


connector_registry = ConnectorRegistry()
