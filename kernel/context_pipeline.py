from __future__ import annotations

from dataclasses import dataclass

from kernel.context.query_rewriter import QueryRewriter
from kernel.context.context_ranker import ContextRanker
from kernel.context.context_compressor import ContextCompressor
from kernel.context_builder import ContextBuilder


@dataclass
class ContextPipelineResult:
    original_query: str
    rewritten_query: str
    compressed_context: str
    build_latency_ms: int


class ContextPipeline:
    def __init__(self) -> None:
        self.rewriter = QueryRewriter()
        self.builder = ContextBuilder()
        self.ranker = ContextRanker()
        self.compressor = ContextCompressor()

    async def run(
        self,
        query: str,
        session_id: str = "",
        user_id: str = "",
        history: list[dict[str, str]] | None = None,
        enable_web: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> ContextPipelineResult:
        rewritten = await self.rewriter.rewrite(query)
        unified = await self.builder.build(
            query=rewritten,
            session_id=session_id,
            history=history or [],
            user_id=user_id,
            enable_web=enable_web,
            metadata=metadata or {},
        )
        ranked = self.ranker.rank(unified.all_chunks(top_k=20), top_k=8)
        compressed = self.compressor.compress(ranked, max_chars=6000)
        return ContextPipelineResult(
            original_query=query,
            rewritten_query=rewritten,
            compressed_context=compressed,
            build_latency_ms=unified.build_latency_ms,
        )
