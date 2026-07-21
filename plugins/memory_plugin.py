"""
MemoryPlugin — 记忆检索插件
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from infra.observability.logger import get_logger
from plugins.base import BasePlugin, PluginResult

if TYPE_CHECKING:
    from kernel.context_builder import UnifiedContext

logger = get_logger(__name__)


class MemoryPlugin(BasePlugin):
    name = "memory"
    description = "从多级记忆系统检索相关历史信息"

    async def execute(self, query: str, context: "UnifiedContext") -> PluginResult:
        t0 = time.monotonic()
        chunks = context.memory[:5]
        content = "\n".join(c.content[:300] for c in chunks) if chunks else ""
        confidence = max((c.confidence for c in chunks), default=0.0) if chunks else 0.0
        return PluginResult(
            plugin_name=self.name,
            content=content,
            confidence=confidence,
            source_type="memory",
            metadata={"chunk_count": len(chunks)},
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
