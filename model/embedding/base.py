"""
Embedding provider interface + DashScope SDK embedding + HTTP fallback + hash fallback.
"""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from infra.config.settings import settings
from infra.observability.logger import get_logger
from model.dashscope_utils import dashscope_proxy_allowlist, resolve_dashscope_api_key

logger = get_logger(__name__)


class BaseEmbedder(ABC):
    @abstractmethod
    async def embed(self, texts: list[str], input_type: str = "query") -> list[list[float]]:
        """Return one embedding vector per input text.

        Args:
            texts: List of texts to embed.
            input_type: \"query\" for search queries, \"document\" for documents to be indexed.
        """

    async def embed_one(self, text: str, input_type: str = "query") -> list[float]:
        results = await self.embed([text], input_type=input_type)
        return results[0]

    async def embed_single(self, text: str) -> list[float]:
        return await self.embed_one(text)


def normalize_embedding_vector(vec: list[float], dims: int) -> list[float]:
    if dims <= 0:
        return list(vec)
    if len(vec) == dims:
        return list(vec)
    if len(vec) > dims:
        return list(vec[:dims])
    return list(vec) + [0.0] * (dims - len(vec))


class HashEmbedder(BaseEmbedder):
    def __init__(self, dims: int = 384) -> None:
        self.dims = dims

    async def embed(self, texts: list[str], input_type: str = "query") -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode()).digest()
        rng = np.random.default_rng(np.frombuffer(seed[:8], dtype=np.uint64)[0])
        vec = rng.standard_normal(self.dims).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()


class DashScopeEmbedder(BaseEmbedder):
    def __init__(self, model: str, dims: int) -> None:
        self.model = model
        self.dims = dims

    async def embed(self, texts: list[str], input_type: str = "query") -> list[list[float]]:
        try:
            import dashscope
        except Exception as exc:  # noqa: BLE001
            logger.warning("dashscope sdk unavailable; falling back to hash", error=str(exc))
            return await HashEmbedder(self.dims).embed(texts)

        api_key = resolve_dashscope_api_key(settings.embedding_api_key, os.getenv("DASHSCOPE_API_KEY"), os.getenv("dashscope_api_key"))
        if api_key:
            dashscope.api_key = api_key
        else:
            logger.warning("dashscope embedding missing api key; falling back to hash")
            return await HashEmbedder(self.dims).embed(texts)

        # Collect all available embedding classes from the SDK.
        embedding_classes: list = []
        for attr in ("TextEmbedding", "MultimodalEmbedding", "Embedding"):
            cls = getattr(dashscope, attr, None)
            if cls is not None:
                embedding_classes.append((attr, cls))

        if not embedding_classes:
            logger.warning("dashscope embedding class missing; falling back to hash")
            return await HashEmbedder(self.dims).embed(texts)

        # Build call-kwargs candidates — for VL embedding models, include input_type.
        is_vl_model = "vl-embedding" in (self.model or "").lower()
        kwargs_candidates: list[dict] = [
            {"model": self.model, "input": texts},
            {"model": self.model, "texts": texts},
            {"model": self.model, "input": {"texts": texts}},
        ]
        if is_vl_model:
            # qwen3-vl-embedding benefits from explicit input_type
            kwargs_candidates.insert(0, {"model": self.model, "input": texts, "input_type": input_type})
            kwargs_candidates.insert(0, {"model": self.model, "texts": texts, "input_type": input_type})

        if is_vl_model and api_key:
            try:
                http_embedder = APIEmbedder(
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key=api_key,
                    model=self.model,
                    dims=self.dims,
                    paths=["/embeddings"],
                    api_style="dashscope",
                )
                return await http_embedder.embed(texts, input_type=input_type)
            except Exception as http_exc:
                logger.debug(
                    "dashscope VL HTTP embedding failed, trying SDK",
                    error=str(http_exc),
                    model=self.model,
                )

        try:
            import asyncio

            loop = asyncio.get_event_loop()

            def _extract_items(data: Any) -> list:
                if data is None:
                    return []
                if isinstance(data, list):
                    return data
                if not isinstance(data, dict):
                    return []
                for key in ("embeddings", "data", "results"):
                    items = data.get(key)
                    if items:
                        return items if isinstance(items, list) else [items]
                return []

            def _item_embedding(item: Any) -> list:
                if isinstance(item, (list, tuple)):
                    return list(item)
                if not isinstance(item, dict):
                    return []
                for key in (
                    "embedding",
                    "vector",
                    "embedding_vector",
                    "text_embedding",
                ):
                    emb = item.get(key)
                    if emb is not None:
                        return list(emb)
                return []

            def _call_batch() -> list[list[float]]:
                last_err: Exception | None = None
                for _attr_name, embedding_call in embedding_classes:
                    for kwargs in kwargs_candidates:
                        try:
                            resp = embedding_call.call(**kwargs)  # type: ignore[attr-defined]
                            output = getattr(resp, "output", None)
                            if output is None and isinstance(resp, dict):
                                output = resp.get("output")
                            if output is None:
                                output = resp
                            items = _extract_items(output)
                            if not items and isinstance(resp, dict):
                                items = _extract_items(resp)
                            vecs: list[list[float]] = []
                            for item in items:
                                emb = _item_embedding(item)
                                if emb:
                                    vecs.append(normalize_embedding_vector(emb, self.dims))
                            if vecs:
                                return vecs
                        except Exception as exc:
                            last_err = exc
                            continue
                raise RuntimeError(
                    f"No compatible dashscope embedding response shape across "
                    f"{[a for a, _ in embedding_classes]} for model={self.model}"
                ) from last_err

            def _call_batch_with_proxy() -> list[list[float]]:
                with dashscope_proxy_allowlist():
                    return _call_batch()

            vecs = await loop.run_in_executor(None, _call_batch_with_proxy)
            if len(vecs) != len(texts):
                raise RuntimeError("dashscope embedding returned mismatched count")
            return vecs
        except Exception as exc:  # noqa: BLE001
            logger.warning("dashscope embedding failed; falling back to hash", error=str(exc), model=self.model)
            return await HashEmbedder(self.dims).embed(texts)


class APIEmbedder(BaseEmbedder):
    """OpenAI-compatible embedding API fallback."""

    def __init__(self, base_url: str, api_key: str, model: str = "text-embedding-v3", dims: int = 384, timeout: int = 30, batch_size: int = 32, paths: list[str] | None = None, trust_env: bool = True, skip_proxy_first: bool = True, api_style: str = "openai") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dims = dims
        self.timeout = timeout
        self.batch_size = batch_size
        self.paths = paths or ["/embeddings", "/v1/embeddings"]
        self.trust_env = trust_env
        self.skip_proxy_first = skip_proxy_first
        self.api_style = api_style

    def _endpoint_candidates(self) -> list[str]:
        return [f"{self.base_url}{p}" for p in self.paths]

    async def _post(self, client, url: str, batch: list[str], input_type: str = "query") -> list[list[float]]:
        payload = {"input": batch, "model": self.model}
        if self.api_style == "dashscope":
            payload = {"input": batch, "model": self.model, "input_type": input_type}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        return [normalize_embedding_vector(item.get("embedding", []), self.dims) for item in items]

    async def embed(self, texts: list[str], input_type: str = "query") -> list[list[float]]:
        import httpx

        results: list[list[float]] = []
        timeout = httpx.Timeout(connect=min(15.0, float(self.timeout)), read=float(self.timeout), write=min(15.0, float(self.timeout)), pool=min(15.0, float(self.timeout)))
        clients = [
            httpx.AsyncClient(timeout=timeout, trust_env=self.trust_env and not self.skip_proxy_first, limits=httpx.Limits(max_keepalive_connections=10, max_connections=50)),
            httpx.AsyncClient(timeout=timeout, trust_env=self.trust_env, limits=httpx.Limits(max_keepalive_connections=10, max_connections=50)),
        ]
        try:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                last_exc: Exception | None = None
                for endpoint in self._endpoint_candidates():
                    for client in clients:
                        try:
                            results.extend(await self._post(client, endpoint, batch, input_type=input_type))
                            last_exc = None
                            break
                        except Exception as exc:  # noqa: BLE001
                            last_exc = exc
                    if last_exc is None:
                        break
                if last_exc is not None:
                    logger.warning("Embedding endpoint failed; using hash fallback", error=str(last_exc), model=self.model)
                    results.extend(await HashEmbedder(self.dims).embed(batch))
            return results
        finally:
            for client in clients:
                await client.aclose()


class LocalEmbedder(BaseEmbedder):
    def __init__(self, model_name: str = "BAAI/bge-m3", dims: int = 384) -> None:
        self.model_name = model_name
        self.dims = dims
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
                self._model = SentenceTransformer(self.model_name)
                logger.info("LocalEmbedder loaded", model=self.model_name)
            except ImportError:
                logger.warning("sentence-transformers not installed; falling back to hash")
                self._model = False
        return self._model

    async def embed(self, texts: list[str], input_type: str = "query") -> list[list[float]]:
        import asyncio

        model = self._load()
        if not model:
            return await HashEmbedder(self.dims).embed(texts)
        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(None, lambda: model.encode(texts, normalize_embeddings=True).tolist())
        return [normalize_embedding_vector(vec, self.dims) for vec in vecs]


def get_embedder() -> BaseEmbedder:
    provider = settings.embedding_provider.lower()
    if provider == "dashscope":
        return DashScopeEmbedder(model=settings.embedding_model_name, dims=settings.embedding_dims)
    if provider in {"api", "openai"} and settings.embedding_base_url:
        return APIEmbedder(base_url=settings.embedding_base_url, api_key=settings.embedding_api_key, model=settings.embedding_model_name, dims=settings.embedding_dims, timeout=settings.embedding_timeout_seconds, paths=[p.strip() for p in settings.embedding_api_paths.split(",") if p.strip()], trust_env=settings.embedding_trust_env, skip_proxy_first=settings.embedding_skip_proxy_first, api_style="openai")
    if provider == "local":
        return LocalEmbedder(model_name=settings.embedding_model_name, dims=settings.embedding_dims)
    if provider != "hash":
        logger.warning("Unknown embedding provider '%s', using hash", provider)
    return HashEmbedder(dims=settings.embedding_dims)
