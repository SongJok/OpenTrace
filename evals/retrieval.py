"""RAG 检索质量的确定性离线指标。"""

from __future__ import annotations

import math
from typing import Any


def normalize_retrieved_ids(value: Any) -> list[str]:
    """把字符串或证据对象列表归一为稳定 ID，并保持首次出现顺序。"""

    if not isinstance(value, list | tuple):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            raw = next(
                (
                    item.get(key)
                    for key in (
                        "id",
                        "ref_id",
                        "claim_id",
                        "chunk_id",
                        "knowledge_page_id",
                        "document_id",
                    )
                    if item.get(key) not in (None, "")
                ),
                "",
            )
        else:
            raw = item
        identifier = str(raw or "").strip()
        if identifier and identifier not in seen:
            seen.add(identifier)
            normalized.append(identifier)
    return normalized


def retrieval_quality_metrics(
    retrieved_ids: list[str],
    relevant_ids: list[str],
    *,
    k: int,
) -> dict[str, float]:
    """计算二元相关性下的 Precision/Recall/MRR/nDCG/HitRate@K。"""

    cutoff = max(1, int(k))
    retrieved = normalize_retrieved_ids(retrieved_ids)[:cutoff]
    relevant = set(normalize_retrieved_ids(relevant_ids))
    if not relevant:
        return {
            "precision_at_k": 0.0,
            "recall_at_k": 0.0,
            "mrr_at_k": 0.0,
            "ndcg_at_k": 0.0,
            "hit_rate_at_k": 0.0,
            "irrelevant_at_k": float(len(retrieved)),
        }

    hit_ranks = [rank for rank, identifier in enumerate(retrieved, 1) if identifier in relevant]
    hit_count = len(hit_ranks)
    dcg = sum(1.0 / math.log2(rank + 1) for rank in hit_ranks)
    ideal_hits = min(len(relevant), cutoff)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return {
        "precision_at_k": hit_count / cutoff,
        "recall_at_k": hit_count / len(relevant),
        "mrr_at_k": 1.0 / hit_ranks[0] if hit_ranks else 0.0,
        "ndcg_at_k": dcg / ideal_dcg if ideal_dcg else 0.0,
        "hit_rate_at_k": 1.0 if hit_ranks else 0.0,
        "irrelevant_at_k": float(len(retrieved) - hit_count),
    }
