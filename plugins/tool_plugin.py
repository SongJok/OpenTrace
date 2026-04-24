"""
ToolPlugin — tool/function-call execution plugin.
Dispatches registered tools via the ToolRegistry.
Triggered by TOOL and MULTI_AGENT routes.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from infra.observability.logger import get_logger
from plugins.base import BasePlugin, PluginResult

if TYPE_CHECKING:
    from kernel.context_builder import UnifiedContext

logger = get_logger(__name__)


class ToolPlugin(BasePlugin):
    name = "tool"
    description = "执行注册工具（计算器、时间、外部API等）"

    async def execute(self, query: str, context: "UnifiedContext") -> PluginResult:
        t0 = time.monotonic()
        tools_available = context.tools or []
        result_lines: list[str] = []

        for tool_name in tools_available[:3]:
            try:
                output = await self._call_tool(tool_name, query)
                if output:
                    result_lines.append(f"[{tool_name}] {output}")
            except Exception as exc:
                logger.debug("Tool call failed", tool=tool_name, error=str(exc))

        content = "\n".join(result_lines)
        return PluginResult(
            plugin_name=self.name,
            content=content,
            confidence=0.9 if content else 0.0,
            source_type="tool",
            metadata={"tools_called": tools_available},
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def _call_tool(self, tool_name: str, query: str) -> str:
        """Dispatch to ToolRegistry. Returns empty string on miss."""
        try:
            from tools.registry.registry import ToolRegistry
            registry = ToolRegistry.get_instance()
            tool = registry.get(tool_name)
            if tool is None:
                return ""
            result = await tool.run({"query": query})
            return str(result) if result is not None else ""
        except Exception as exc:
            logger.debug("ToolRegistry dispatch failed", tool=tool_name, error=str(exc))
            return ""
