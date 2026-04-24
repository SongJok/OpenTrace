from __future__ import annotations

from .models import Citation, WebDocument


class CitationBuilder:
    def build(self, docs: list[WebDocument], max_items: int = 5) -> list[Citation]:
        out: list[Citation] = []
        for i, d in enumerate(docs[:max_items], 1):
            out.append(Citation(id=i, title=d.title or d.url, url=d.url, snippet=d.snippet[:160]))
        return out
