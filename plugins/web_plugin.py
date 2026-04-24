"""
WebPlugin — 联网搜索认知插件
必须通过 Cognitive Kernel 调用，禁止绕过。
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from infra.observability.logger import get_logger
from plugins.base import BasePlugin, PluginResult

if TYPE_CHECKING:
    from kernel.context_builder import ContextChunk, UnifiedContext

logger = get_logger(__name__)


class WebPlugin(BasePlugin):
    name = "web"
    description = "实时搜索互联网获取最新信息"

    async def execute(self, query: str, context: "UnifiedContext") -> PluginResult:
        t0 = time.monotonic()
        chunks = await self.search_chunks(query)
        content = "\n\n".join(
            f"[网页{i+1}] {c.content[:500]}" for i, c in enumerate(chunks)
        )
        confidence = min(0.5 + len(chunks) * 0.1, 0.9) if chunks else 0.0
        return PluginResult(
            plugin_name=self.name,
            content=content,
            confidence=confidence,
            source_type="web",
            metadata={"sources": [c.metadata.get("url", "") for c in chunks]},
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def search_chunks(self, query: str, top_k: int = 3) -> list["ContextChunk"]:
        from kernel.context_builder import ContextChunk
        try:
            import httpx
            from infra.config.settings import get_settings
            settings = get_settings()
            api_key = (
                getattr(settings, "serper_api_key", None)
                or os.getenv("SERPER_API_KEY")
                or os.getenv("serper_api_key")
            )
            if isinstance(api_key, str):
                api_key = api_key.strip()
            if not api_key:
                logger.warning("WebPlugin disabled: SERPER_API_KEY not configured")
                return []
            async with httpx.AsyncClient(trust_env=False, timeout=10.0) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": top_k},
                )
                data = resp.json()
            return [
                ContextChunk(
                    content=r.get("snippet", r.get("title", ""))[:800],
                    source_type="web",
                    score=0.75,
                    confidence=0.70,
                    metadata={"url": r.get("link", ""), "title": r.get("title", "")},
                )
                for r in data.get("organic", [])[:top_k]
            ]
        except Exception as exc:
            logger.debug("WebPlugin failed", error=str(exc))
            return []
