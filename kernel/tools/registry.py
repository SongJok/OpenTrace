"""
DEPRECATED — kernel/tools/registry.py

This registry has been superseded by kernel.runtime.capability.CapabilityRegistry
(Phase 1.3).  Maintained for backward compatibility — new code should use
`capability_registry` from kernel.runtime.capability.
"""

from __future__ import annotations

from .base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self.tools.get(name)

    def list(self) -> list[BaseTool]:
        return list(self.tools.values())


tool_registry = ToolRegistry()
