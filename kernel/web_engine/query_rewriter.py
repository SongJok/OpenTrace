from __future__ import annotations


class QueryRewriter:
    def rewrite(self, query: str) -> list[str]:
        q = (query or "").strip()
        if not q:
            return []

        variants = [q]
        lower = q.lower()

        time_sensitive = any(
            k in lower
            for k in [
                "latest",
                "today",
                "news",
                "current",
                "breaking",
                "最近",
                "今日",
                "最新",
                "新闻",
            ]
        )
        if time_sensitive:
            variants.append(f"{q} latest news")
            variants.append(f"{q} 2026 update")

        if any(k in lower for k in ["trend", "trends", "趋势"]):
            variants.append(f"{q} analysis report")

        seen = set()
        out: list[str] = []
        for v in variants:
            if v not in seen:
                out.append(v)
                seen.add(v)
        return out[:3]
