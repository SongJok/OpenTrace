from __future__ import annotations

import os

import httpx

from .models import SearchResult


class SearchClient:
    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        api_key = (os.getenv("SERPER_API_KEY") or os.getenv("serper_api_key") or "").strip()
        if not api_key:
            return []

        async with httpx.AsyncClient(trust_env=False, timeout=10.0) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": top_k},
            )
            resp.raise_for_status()
            data = resp.json()

        out: list[SearchResult] = []
        for item in data.get("organic", [])[:top_k]:
            out.append(
                SearchResult(
                    title=str(item.get("title", "")),
                    url=str(item.get("link", "")),
                    snippet=str(item.get("snippet", "")),
                )
            )
        return out
