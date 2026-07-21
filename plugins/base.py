"""
Plugin base interface — 所有插件必须实现此接口
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.context_builder import UnifiedContext


@dataclass
class PluginResult:
    plugin_name: str
    content: str
    confidence: float = 1.0       # 0.0 - 1.0
    source_type: str = "unknown"  # memory|document|web|tool|knowledge
    metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


class BasePlugin(ABC):
    name: str = "base"
    description: str = ""
    version: str = "1.0"

    @abstractmethod
    async def execute(self, query: str, context: "UnifiedContext") -> PluginResult:
        """所有插件必须实现。返回 PluginResult。"""
        ...

    async def health_check(self) -> bool:
        return True
