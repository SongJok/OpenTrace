"""
Plugin SDK — lightweight base for building OpenTrace plugins.
Plugins extend the tool registry with new capabilities.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from tools.registry.registry import ToolSpec, registry as global_registry


@dataclass
class PluginManifest:
    """Metadata that every plugin must declare."""
    plugin_id: str
    name: str
    version: str
    description: str
    author: str = ""
    tags: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)  # other plugin IDs


class BasePlugin(ABC):
    """
    Abstract base class for all OpenTrace plugins.

    Subclass this and implement:
      - manifest: PluginManifest property
      - register_tools(): register tools into the global registry
      - setup(config): optional async initialisation
      - teardown(): optional async cleanup
    """

    @property
    @abstractmethod
    def manifest(self) -> PluginManifest:
        ...

    @abstractmethod
    def register_tools(self) -> None:
        """Register plugin tools into the global ToolRegistry."""

    async def setup(self, config: Optional[dict[str, Any]] = None) -> None:
        """Called once at plugin load time."""

    async def teardown(self) -> None:
        """Called at shutdown."""

    def tool(
        self,
        name: str,
        description: str,
        tags: Optional[list[str]] = None,
    ) -> Callable:
        """Convenience decorator — registers a tool under this plugin."""
        full_tags = (tags or []) + [self.manifest.plugin_id]
        return global_registry.tool(name=name, description=description, tags=full_tags)


class PluginRegistry:
    """Tracks installed plugins and manages their lifecycle."""

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}

    async def install(
        self,
        plugin: BasePlugin,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        pid = plugin.manifest.plugin_id
        if pid in self._plugins:
            raise ValueError(f"Plugin '{pid}' already installed")
        await plugin.setup(config)
        plugin.register_tools()
        self._plugins[pid] = plugin

    async def uninstall(self, plugin_id: str) -> None:
        plugin = self._plugins.pop(plugin_id, None)
        if plugin:
            await plugin.teardown()

    def get(self, plugin_id: str) -> Optional[BasePlugin]:
        return self._plugins.get(plugin_id)

    def list_installed(self) -> list[PluginManifest]:
        return [p.manifest for p in self._plugins.values()]


# Module-level singleton
plugin_registry = PluginRegistry()
