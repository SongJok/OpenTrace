"""Reciprocal Rank Fusion (RRF) across RAG retrieval lanes."""

from __future__ import annotations

from typing import Any


def _lane_of(item: dict[str, Any]) -> str:
    st = str(item.get("source_type") or "document").lower()
    if st in ("knowledge", "knowledge_page", "knowledge_claim", "knowledge_relation"):
        return "knowledge"
    if st == "llmwiki":
        return "llmwiki"
    if st in ("memory", "semantic_memory"):
        return "memory"
    if st in ("episodic", "episodic_memory"):
        return "episodic"
    return "document"


def _item_key(item: dict[str, Any]) -> str:
    """优先用可追溯实体标识去重，避免不同查询变体的同一片段被当成不同证据。"""

    source_type = str(item.get("source_type") or "document").lower()
    identity_fields = (
        "claim_id",
        "relation_id",
        "knowledge_page_id",
        "chunk_id",
        "id",
    )
    identity = next(
        (str(item.get(field)) for field in identity_fields if item.get(field) not in (None, "")),
        "",
    )
    if source_type in {"document", "llmwiki"}:
        document_id = str(item.get("document_id") or "")
        chunk_index = item.get("chunk_index")
        if document_id and chunk_index is not None:
            identity = f"{document_id}:{chunk_index}"
        elif document_id and item.get("chunk_id"):
            identity = f"{document_id}:{item.get('chunk_id')}"
    if not identity:
        identity = str(item.get("text") or item.get("answer") or "")[:160]
    return f"{source_type}::{identity}"


def _retrieval_list_key(item: dict[str, Any]) -> str:
    lane = _lane_of(item)
    matched_query = str(item.get("matched_query") or item.get("query") or "default").strip()
    return f"{lane}::{matched_query or 'default'}"


def fuse_retrieval_hits(
    items: list[dict[str, Any]],
    *,
    k: int = 60,
    top_n: int = 20,
    lane_weights: dict[str, float] | None = None,
    rank_fusion_enabled: bool = True,
) -> list[dict[str, Any]]:
    """融合多查询、多通道命中，同时保留原始分数和可审计命中轨迹。

    每个 ``lane + matched_query`` 视为一条独立排名列表。同一证据被多个查询变体
    命中时会获得覆盖度增益；通道权重只作用一次，避免先乘权重、融合后再次乘权重。
    """

    if not items:
        return []
    normalized_k = max(1, int(k))
    normalized_top_n = max(1, int(top_n))
    weights = {
        str(key): max(0.0, float(value or 0.0)) for key, value in (lane_weights or {}).items()
    }

    retrieval_lists: dict[str, list[dict[str, Any]]] = {}
    list_lanes: dict[str, str] = {}
    for raw in items:
        row = dict(raw)
        list_key = _retrieval_list_key(row)
        list_lanes[list_key] = _lane_of(row)
        retrieval_lists.setdefault(list_key, []).append(row)

    # 单条检索列表内先按实体去重，保留该查询对同一证据的最高分。
    for list_key, rows in list(retrieval_lists.items()):
        best_by_item: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = _item_key(row)
            current = best_by_item.get(key)
            row_score = float(row.get("raw_score", row.get("score", 0.0)) or 0.0)
            current_score = (
                float(current.get("raw_score", current.get("score", 0.0)) or 0.0)
                if current is not None
                else -1.0
            )
            if current is None or row_score > current_score:
                best_by_item[key] = row
        retrieval_lists[list_key] = sorted(
            best_by_item.values(),
            key=lambda row: float(row.get("raw_score", row.get("score", 0.0)) or 0.0),
            reverse=True,
        )

    lists_per_lane: dict[str, int] = {}
    for lane in list_lanes.values():
        lists_per_lane[lane] = lists_per_lane.get(lane, 0) + 1

    aggregates: dict[str, dict[str, Any]] = {}
    for list_key, rows in retrieval_lists.items():
        lane = list_lanes[list_key]
        lane_weight = weights.get(lane, 1.0)
        for rank, row in enumerate(rows, start=1):
            key = _item_key(row)
            raw_score = min(
                1.0,
                max(0.0, float(row.get("raw_score", row.get("score", 0.0)) or 0.0)),
            )
            aggregate = aggregates.setdefault(
                key,
                {
                    "row": row,
                    "raw_score": raw_score,
                    "rrf_raw": 0.0,
                    "hit_count": 0,
                    "matched_queries": [],
                    "ranks": [],
                    "lane": lane,
                },
            )
            if raw_score > float(aggregate["raw_score"]):
                aggregate["row"] = row
                aggregate["raw_score"] = raw_score
            aggregate["rrf_raw"] += lane_weight / (normalized_k + rank)
            aggregate["hit_count"] += 1
            aggregate["ranks"].append(rank)
            matched_query = str(row.get("matched_query") or row.get("query") or "").strip()
            if matched_query and matched_query not in aggregate["matched_queries"]:
                aggregate["matched_queries"].append(matched_query)

    out: list[dict[str, Any]] = []
    for aggregate in aggregates.values():
        row = dict(aggregate["row"])
        lane = str(aggregate["lane"])
        lane_weight = weights.get(lane, 1.0)
        raw_score = float(aggregate["raw_score"])
        weighted_score = min(1.0, raw_score * lane_weight)
        ideal_rrf = lists_per_lane.get(lane, 1) * lane_weight / (normalized_k + 1)
        rank_score = min(1.0, float(aggregate["rrf_raw"]) / max(ideal_rrf, 1e-9))
        # 排名信号只能校准相对顺序，不能把低相关证据抬过绝对相关性门槛。
        # 多查询稳定命中的证据保留完整分数，只命中少数变体的证据最多下调 20%。
        score = (
            weighted_score * (0.80 + 0.20 * rank_score) if rank_fusion_enabled else weighted_score
        )
        row["raw_score"] = round(raw_score, 6)
        row["lane_weight"] = round(lane_weight, 4)
        row["weighted_score"] = round(weighted_score, 6)
        row["rrf_raw_score"] = round(float(aggregate["rrf_raw"]), 8)
        row["rrf_score"] = round(rank_score if rank_fusion_enabled else 0.0, 6)
        row["retrieval_hit_count"] = int(aggregate["hit_count"])
        row["retrieval_ranks"] = list(aggregate["ranks"])
        row["matched_queries"] = list(aggregate["matched_queries"])
        row["score"] = round(min(1.0, max(0.0, score)), 6)
        out.append(row)

    out.sort(
        key=lambda row: (
            -float(row.get("score", 0.0) or 0.0),
            -int(row.get("retrieval_hit_count", 0) or 0),
            _item_key(row),
        )
    )
    return out[:normalized_top_n]


def reciprocal_rank_fusion(
    items: list[dict[str, Any]],
    *,
    k: int = 60,
    top_n: int = 20,
    lane_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """兼容入口：执行校准后的加权 RRF。"""

    return fuse_retrieval_hits(
        items,
        k=k,
        top_n=top_n,
        lane_weights=lane_weights,
        rank_fusion_enabled=True,
    )
