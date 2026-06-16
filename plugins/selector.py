"""
PluginSelector — 根据路由决策选择插件组合

Plugins are also registered into the unified CapabilityRegistry
(kernel.runtime.capability) for orchestrator visibility.
"""
from __future__ import annotations

from plugins.base import BasePlugin
from infra.observability.logger import get_logger

logger = get_logger(__name__)

PLUGIN_RULES: dict[str, list[str]] = {
    "FAST":        ["memory"],
    "REASON":      ["memory", "document", "knowledge"],
    "TOOL":        ["tool", "memory"],
    "WEB":         ["web", "memory"],
    "MULTI_AGENT": ["memory", "document", "web", "tool"],
    "direct":      ["memory"],
}

_REGISTRY: dict[str, type[BasePlugin]] = {}


def _build_registry() -> dict[str, type[BasePlugin]]:
    reg: dict[str, type[BasePlugin]] = {}
    from plugins.memory_plugin import MemoryPlugin
    from plugins.document_plugin import DocumentPlugin
    from plugins.web_plugin import WebPlugin
    reg["memory"] = MemoryPlugin
    reg["document"] = DocumentPlugin
    reg["web"] = WebPlugin
    try:
        from plugins.tool_plugin import ToolPlugin
        reg["tool"] = ToolPlugin
    except ImportError:
        pass
    try:
        from plugins.knowledge_plugin import KnowledgePlugin
        reg["knowledge"] = KnowledgePlugin
    except ImportError:
        pass
    return reg


def _ensure_registry() -> None:
    global _REGISTRY
    if _REGISTRY:
        return
    _REGISTRY = _build_registry()
    # Register each plugin class into the unified CapabilityRegistry
    try:
        from kernel.runtime.capability import capability_registry

        for name, cls in _REGISTRY.items():
            capability_registry.register_plugin(name, cls)
    except ImportError:
        pass


class PluginSelector:
    @staticmethod
    async def select(route: str) -> list[BasePlugin]:
        _ensure_registry()
        names = PLUGIN_RULES.get(route, PLUGIN_RULES["REASON"])
        plugins: list[BasePlugin] = []
        for name in names:
            cls = _REGISTRY.get(name)
            if cls:
                plugins.append(cls())
            else:
                logger.debug("Plugin not registered", name=name)
        logger.info("PluginSelector.select", route=route, selected=[p.name for p in plugins])
        return plugins
