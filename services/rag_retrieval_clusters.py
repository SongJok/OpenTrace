"""Evidence clustering for RAG fusion — group by source / topic stub."""

from __future__ import annotations

import hashlib
from typing import Any


def cluster_evidence_chunks(
    chunks: list[dict[str, Any]],
    *,
    max_clusters: int = 8,
) -> dict[str, Any]:
    """Deterministic clustering by source prefix + content hash bucket."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for c in chunks:
        src = str(c.get("source") or c.get("document_id") or "unknown")[:40]
        body = str(c.get("content") or c.get("snippet") or "")[:120]
        key = hashlib.md5(f"{src}:{body}".encode()).hexdigest()[:8]
        bucket_id = f"{src}:{key}"
        buckets.setdefault(bucket_id, []).append(c)

    clusters = []
    for cid, items in list(buckets.items())[:max_clusters]:
        clusters.append(
            {
                "cluster_id": cid,
                "size": len(items),
                "representative": str(items[0].get("content") or items[0].get("snippet") or "")[:200],
                "source": str(items[0].get("source", "")),
            }
        )
    return {
        "cluster_count": len(clusters),
        "clusters": clusters,
        "total_chunks": len(chunks),
    }