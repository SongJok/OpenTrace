"""
KnowledgePlugin — semantic knowledge-base retrieval plugin.
Searches the semantic memory store for relevant knowledge chunks.
Triggered by REASON and MULTI_AGENT routes.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from infra.observability.logger import get_logger
from plugins.base import BasePlugin, PluginResult

if TYPE_CHECKING:
    from kernel.context_builder import UnifiedContext

logger = get_logger(__name__)


class KnowledgePlugin(BasePlugin):
    name = "knowledge"
    description = "从语义知识库检索相关知识"

    async def execute(self, query: str, context: "UnifiedContext") -> PluginResult:
        t0 = time.monotonic()
        chunks = context.knowledge[:5]
        content = "\n\n".join(
            f"[知识片段 {i + 1}] {c.content[:400]}" for i, c in enumerate(chunks)
        )
        confidence = max((c.confidence for c in chunks), default=0.0) if chunks else 0.0
        return PluginResult(
            plugin_name=self.name,
            content=content,
            confidence=confidence,
            source_type="knowledge",
            metadata={"chunk_count": len(chunks)},
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
