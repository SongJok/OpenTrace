from __future__ import annotations

from .models import SearchResult, WebDocument


class Ranker:
    def rank(self, query: str, items: list[SearchResult]) -> list[WebDocument]:
        q = (query or "").lower()
        docs: list[WebDocument] = []
        for r in items:
            url = r.url.lower()
            score = 0.0
            if q and q in (r.title + " " + r.snippet).lower():
                score += 1.0
            if any(h in url for h in [".gov", ".edu", "reuters", "apnews", "bbc", "nytimes", "wsj"]):
                score += 1.2
            if any(k in url for k in ["news", "blog", "official"]):
                score += 0.4
            docs.append(
                WebDocument(
                    title=r.title,
                    url=r.url,
                    snippet=r.snippet,
                    score=score,
                )
            )
        docs.sort(key=lambda d: d.score, reverse=True)
        return docs
