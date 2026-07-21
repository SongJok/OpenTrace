"""
Reranker interface + DashScope SDK reranker + HTTP fallback + BM25 heuristic fallback.
"""
from __future__ import annotations

import math
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from infra.config.settings import settings
from infra.observability.logger import get_logger
from model.dashscope_utils import dashscope_proxy_allowlist, resolve_dashscope_api_key

logger = get_logger(__name__)


@dataclass
class RankedResult:
    index: int
    score: float
    text: str


class BaseReranker(ABC):
    @abstractmethod
    async def rerank(self, query: str, candidates: list[str], top_k: int = 5) -> list[RankedResult]:
        """Return top_k candidates sorted by relevance descending."""


class HeuristicReranker(BaseReranker):
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    async def rerank(self, query: str, candidates: list[str], top_k: int = 5) -> list[RankedResult]:
        if not candidates:
            return []
        query_terms = self._tokenize(query)
        avg_dl = sum(len(self._tokenize(c)) for c in candidates) / len(candidates)
        scored = [
            RankedResult(index=i, score=self._bm25(query_terms, self._tokenize(doc), len(self._tokenize(doc)), avg_dl), text=doc)
            for i, doc in enumerate(candidates)
        ]
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\w+", text.lower())

    def _bm25(self, q_terms: list[str], d_terms: list[str], dl: int, avg_dl: float) -> float:
        tf_map: dict[str, int] = {}
        for t in d_terms:
            tf_map[t] = tf_map.get(t, 0) + 1
        score = 0.0
        for term in set(q_terms):
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            idf = math.log(1 + 1.0 / (0.5 + tf))
            num = tf * (self.k1 + 1)
            den = tf + self.k1 * (1 - self.b + self.b * dl / max(avg_dl, 1))
            score += idf * num / den
        return score


class DashScopeReranker(BaseReranker):
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self.api_key = api_key
        self._fallback = HeuristicReranker()

    async def rerank(self, query: str, candidates: list[str], top_k: int = 5) -> list[RankedResult]:
        if not candidates:
            return []
        try:
            import dashscope
            from http import HTTPStatus

            dashscope.api_key = resolve_dashscope_api_key(self.api_key, os.getenv("DASHSCOPE_API_KEY"), os.getenv("dashscope_api_key"))
            if not dashscope.api_key:
                logger.warning("dashscope rerank missing api key; using heuristic fallback", model=self.model)
                return await self._fallback.rerank(query, candidates, top_k)
            documents = [{"text": c} for c in candidates]
            with dashscope_proxy_allowlist():
                resp = dashscope.TextReRank.call(
                    model=self.model or "qwen3-vl-rerank",
                    query={"text": query},
                    documents=documents,
                    top_n=top_k,
                    return_documents=True,
                )
            if resp.status_code != HTTPStatus.OK:
                raise RuntimeError(str(resp))
            payload = resp.output.get("results", []) if getattr(resp, "output", None) else []
            results: list[RankedResult] = []
            for item in payload:
                idx = int(item.get("index", 0))
                score = float(item.get("relevance_score", 0.0))
                text = item.get("document", {}).get("text", candidates[idx] if idx < len(candidates) else "")
                results.append(RankedResult(index=idx, score=score, text=text))
            results.sort(key=lambda r: r.score, reverse=True)
            return results[:top_k]
        except Exception as exc:  # noqa: BLE001
            logger.warning("DashScope rerank failed; using heuristic fallback", error=str(exc), model=self.model)
            return await self._fallback.rerank(query, candidates, top_k)


class APIReranker(BaseReranker):
    def __init__(self, api_url: str, api_key: str = "", model: str = "", timeout: int = 10, paths: list[str] | None = None, trust_env: bool = True, skip_proxy_first: bool = True, api_style: str = "openai") -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.paths = paths or ["/rerank", "/v1/rerank"]
        self.trust_env = trust_env
        self.skip_proxy_first = skip_proxy_first
        self.api_style = api_style
        self._fallback = HeuristicReranker()

    def _endpoint_candidates(self) -> list[str]:
        return [f"{self.api_url}{p}" for p in self.paths]

    async def _post(self, client, url: str, query: str, candidates: list[dict], top_k: int) -> list[RankedResult]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict = {"query": query, "documents": candidates, "top_n": top_k, "return_documents": True}
        if self.model:
            payload["model"] = self.model
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        results: list[RankedResult] = []
        for item in data.get("results", []):
            idx = item.get("index", 0)
            score = float(item.get("relevance_score", 0.0))
            doc = item.get("document", {})
            text = doc.get("text", candidates[idx].get("text", "") if idx < len(candidates) else "")
            results.append(RankedResult(index=idx, score=score, text=text))
        return results

    async def rerank(self, query: str, candidates: list[str], top_k: int = 5) -> list[RankedResult]:
        if not candidates:
            return []
        import httpx

        timeout = httpx.Timeout(connect=min(10.0, float(self.timeout)), read=float(self.timeout), write=min(10.0, float(self.timeout)), pool=min(10.0, float(self.timeout)))
        clients = [
            httpx.AsyncClient(timeout=timeout, trust_env=self.trust_env and not self.skip_proxy_first, limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)),
            httpx.AsyncClient(timeout=timeout, trust_env=self.trust_env, limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)),
        ]
        doc_candidates = [{"text": c} for c in candidates]
        try:
            last_exc: Exception | None = None
            for endpoint in self._endpoint_candidates():
                for client in clients:
                    try:
                        return await self._post(client, endpoint, query, doc_candidates, top_k)
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        continue
            logger.warning("Rerank endpoint failed; using heuristic fallback", error=str(last_exc), model=self.model)
            return await self._fallback.rerank(query, candidates, top_k)
        finally:
            for client in clients:
                await client.aclose()


def get_reranker() -> BaseReranker:
    provider = settings.rerank_provider.lower()
    api_key = settings.rerank_api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("dashscope_api_key") or ""
    if provider == "dashscope":
        if not api_key:
            logger.warning("DashScope rerank provider configured but no API key found; using heuristic fallback")
            return HeuristicReranker()
        return DashScopeReranker(model=settings.rerank_model_name, api_key=api_key)
    if provider in {"api", "openai"} and settings.rerank_api_url:
        return APIReranker(
            api_url=settings.rerank_api_url,
            api_key=api_key,
            model=settings.rerank_model_name,
            timeout=settings.rerank_timeout_seconds,
            paths=[p.strip() for p in settings.rerank_api_paths.split(",") if p.strip()],
            trust_env=settings.rerank_trust_env,
            skip_proxy_first=settings.rerank_skip_proxy_first,
            api_style="openai",
        )
    if provider != "heuristic":
        logger.warning("Unknown rerank provider '%s', using heuristic", provider)
    return HeuristicReranker()
