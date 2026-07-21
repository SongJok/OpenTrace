#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

URLS = [
    "https://dashscope.aliyuncs.com/api/v1",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com/api/v1",
    "https://dashscope-us.aliyuncs.com/api/v1",
]


def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


async def _http_get(url: str, trust_env: bool = True) -> tuple[str, int | None, str]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=8.0, trust_env=trust_env) as client:
            resp = await client.get(url)
            return url, resp.status_code, resp.text[:200].replace("\n", " ")
    except Exception as exc:  # noqa: BLE001
        return url, None, f"{type(exc).__name__}: {exc}"


async def _run_http_checks(trust_env: bool) -> list[tuple[str, int | None, str]]:
    return await asyncio.gather(*[_http_get(url, trust_env=trust_env) for url in URLS])


def diagnose_network() -> None:
    _print_header("Network / DNS Diagnostics")
    for raw in URLS:
        host = urlparse(raw).hostname or ""
        try:
            addrs = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
            print(f"{host}: {', '.join(addrs)}")
        except Exception as exc:  # noqa: BLE001
            print(f"{host}: DNS_FAIL {type(exc).__name__}: {exc}")

    results = asyncio.run(_run_http_checks(trust_env=True))
    print("\nHTTP checks with trust_env=True")
    for url, status, info in results:
        print(f"{url} -> {status} | {info}")

    results = asyncio.run(_run_http_checks(trust_env=False))
    print("\nHTTP checks with trust_env=False")
    for url, status, info in results:
        print(f"{url} -> {status} | {info}")


async def test_embedding() -> None:
    from model.embedding.base import get_embedder

    embedder = get_embedder()
    vecs = await embedder.embed(["你好，世界", "DashScope embedding connectivity check"])
    _print_header("Embedding")
    print("provider:", type(embedder).__name__)
    print("count:", len(vecs))
    print("dims:", len(vecs[0]) if vecs else 0)
    print("first_8:", [round(x, 6) for x in vecs[0][:8]] if vecs else [])


async def test_rerank() -> None:
    from model.reranker.base import get_reranker

    reranker = get_reranker()
    items = [
        "这是一段关于向量检索的文本",
        "这是一个完全不相关的句子",
        "DashScope rerank connectivity check",
    ]
    results = await reranker.rerank("向量检索", items, top_k=2)
    _print_header("Rerank")
    print("provider:", type(reranker).__name__)
    print("count:", len(results))
    for item in results:
        print({"index": item.index, "score": round(item.score, 6), "text": item.text})


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate DashScope embedding/rerank clients")
    parser.add_argument("--embedding", action="store_true", help="test embedding only")
    parser.add_argument("--rerank", action="store_true", help="test rerank only")
    parser.add_argument("--diagnose", action="store_true", help="run network diagnostics")
    args = parser.parse_args()

    if not args.embedding and not args.rerank and not args.diagnose:
        args.embedding = True
        args.rerank = True
        args.diagnose = True

    print("DASHSCOPE_API_KEY set:", bool(os.getenv("DASHSCOPE_API_KEY") or os.getenv("EMBEDDING_API_KEY") or os.getenv("RERANK_API_KEY")))
    print("embedding provider env:", os.getenv("EMBEDDING_PROVIDER"))
    print("rerank provider env:", os.getenv("RERANK_PROVIDER"))

    try:
        if args.diagnose:
            diagnose_network()
        if args.embedding:
            asyncio.run(test_embedding())
        if args.rerank:
            asyncio.run(test_rerank())
        return 0
    except Exception as exc:  # noqa: BLE001
        _print_header("ERROR")
        print(type(exc).__name__, str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
