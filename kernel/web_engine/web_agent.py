from __future__ import annotations

import asyncio

from .citation_builder import CitationBuilder
from .models import SearchResult, WebContext
from .query_rewriter import QueryRewriter
from .ranker import Ranker
from .search_client import SearchClient


class WebAgent:
    def __init__(self) -> None:
        self.rewriter = QueryRewriter()
        self.search_client = SearchClient()
        self.ranker = Ranker()
        self.citation_builder = CitationBuilder()

    async def run(self, query: str) -> WebContext:
        queries = self.rewriter.rewrite(query)
        if not queries:
            return WebContext()

        batches = await asyncio.gather(*[self.search_client.search(q, top_k=5) for q in queries], return_exceptions=True)

        merged: list[SearchResult] = []
        seen_urls: set[str] = set()
        for b in batches:
            if isinstance(b, Exception):
                continue
            for r in b:
                if not r.url or r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                merged.append(r)

        ranked = self.ranker.rank(query, merged)
        citations = self.citation_builder.build(ranked)
        return WebContext(documents=ranked[:5], citations=citations)
