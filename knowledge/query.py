"""Knowledge-query planning and scoped retrieval for the orchestration layer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import (
    ChatSession,
    ConversationState,
    KnowledgeClaim,
    KnowledgePage,
    KnowledgeRelation,
    KnowledgeSource,
    KnowledgeSourceVersion,
    User,
)
from knowledge.access import accessible_source_predicate, resolve_access_context
from knowledge.domain import KNOWLEDGE_QUERY_PLAN_VERSION
from services.retrieval_matching import expand_retrieval_terms, semantic_relevance_score

logger = get_logger(__name__)


@dataclass(slots=True)
class KnowledgeQueryPlan:
    query_type: str
    paths: list[str]
    progressive_disclosure: list[str]
    max_hops: int
    candidate_budget: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["version"] = KNOWLEDGE_QUERY_PLAN_VERSION
        return data


def build_knowledge_query_plan(query_type: str, top_k: int) -> KnowledgeQueryPlan:
    paths = ["hot_knowledge", "knowledge_page", "knowledge_claim", "document_evidence"]
    max_hops = 1
    if query_type in {"comparison", "relation"}:
        paths.insert(2, "knowledge_relation")
        max_hops = max(1, min(4, int(getattr(settings, "knowledge_max_relation_hops", 2))))
    elif query_type == "procedure":
        paths = ["hot_knowledge", "knowledge_procedure", "knowledge_claim", "document_evidence"]
    elif query_type == "definition":
        paths = [
            "hot_knowledge",
            "knowledge_term",
            "knowledge_page",
            "knowledge_claim",
            "document_evidence",
        ]
    return KnowledgeQueryPlan(
        query_type=query_type,
        paths=paths,
        progressive_disclosure=["summary", "page", "claim", "source_evidence"],
        max_hops=max_hops,
        candidate_budget=max(
            12,
            min(int(getattr(settings, "knowledge_query_candidate_budget", 60)), top_k * 6),
        ),
        reason="governed knowledge before raw document fallback",
    )


def infer_knowledge_query_type(query: str) -> str:
    """用稳定、低成本的规则识别知识查询类型。"""
    text = (query or "").strip().lower()
    if any(marker in text for marker in ("关系", "关联", "依赖", "影响")):
        return "relation"
    if any(marker in text for marker in ("区别", "对比", "比较", "差异")):
        return "comparison"
    if any(marker in text for marker in ("如何", "怎么", "步骤", "流程", "办理", "操作")):
        return "procedure"
    if any(marker in text for marker in ("是什么", "什么是", "定义", "含义", "概念")):
        return "definition"
    return "factual"


def _tokens(query: str) -> list[str]:
    """为中英文查询生成 ILIKE/FTS 粗召回词，并补充稳定的业务同义表达。

    PostgreSQL ``simple`` 配置不会对中文分词；统一召回词生成器会保留原始语义片段、
    2-4 字窗口和命中业务概念的同义词，不依赖外部分词服务。
    """

    return expand_retrieval_terms(query, limit=32)


def _score(text: str, title: str, tokens: list[str], *, query: str = "") -> float:
    if not tokens:
        return 0.0
    effective_query = query or " ".join(tokens)
    return semantic_relevance_score(effective_query, text, title=title)


def _governed_score(base_score: float, source: KnowledgeSource, authority: str) -> float:
    authority_boost = {
        "official": 0.12,
        "approved": 0.09,
        "verified": 0.06,
        "external": 0.02,
        "contextual": 0.0,
        "inferred": -0.04,
    }.get(authority, 0.0)
    review_penalty = 0.0
    if source.review_due_at is not None and source.review_due_at <= datetime.now(UTC):
        review_penalty = 0.08
    return min(0.999, max(0.0, base_score + authority_boost - review_penalty))


def _source_governance(source: KnowledgeSource) -> dict[str, Any]:
    return {
        "space_id": source.space_id,
        "classification": source.classification,
        "source_system": source.source_system,
        "sync_status": source.sync_status,
        "effective_from": source.effective_from.isoformat() if source.effective_from else None,
        "effective_to": source.effective_to.isoformat() if source.effective_to else None,
        "review_due_at": source.review_due_at.isoformat() if source.review_due_at else None,
    }


def _owner_filter(column, user_id: str):
    if not user_id or user_id == "shared":
        return None
    return column == user_id


async def search_knowledge(
    *,
    query: str,
    user_id: str,
    tenant_id: str | None,
    workspace_id: str | None,
    project_id: str | None = None,
    space_id: str | None = None,
    knowledge_space_ids: Sequence[str] | None = None,
    top_k: int,
    query_type: str | None = None,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve governed knowledge in progressive-disclosure order.

    Pages are returned as summaries first, followed by traceable claims.  For
    relation/comparison questions, published graph edges are included as a
    third stage.  Passing ``knowledge_space_ids`` creates an explicit scope;
    it is intersected with the user's ACL and an empty scope fails closed.
    """

    tokens = _tokens(query)
    if not tokens:
        return []
    tenant = (tenant_id or "default").strip() or "default"
    workspace = (workspace_id or "default").strip() or "default"
    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id) if user_id and user_id != "shared" else None
            access_context = (
                await resolve_access_context(
                    db,
                    user=user,
                    tenant_id=tenant,
                    workspace_id=workspace,
                    project_id=project_id,
                )
                if user is not None
                else None
            )
            if access_context is None:
                return []
            explicit_space_scope = knowledge_space_ids is not None or bool(space_id)
            requested_space_ids = list(
                dict.fromkeys(
                    str(item).strip() for item in (knowledge_space_ids or ()) if str(item).strip()
                )
            )
            if space_id:
                normalized_space_id = space_id.strip()
                if knowledge_space_ids is None:
                    requested_space_ids = [normalized_space_id]
                else:
                    requested_space_ids = [
                        item for item in requested_space_ids if item == normalized_space_id
                    ]
            if explicit_space_scope:
                if access_context is None or not requested_space_ids:
                    return []
                accessible_space_ids = set(access_context.accessible_space_ids)
                requested_space_ids = [
                    item for item in requested_space_ids if item in accessible_space_ids
                ]
                if not requested_space_ids:
                    return []
            source_access = (
                accessible_source_predicate(access_context, project_id=project_id)
                if access_context is not None
                else None
            )
            if knowledge_space_ids is None:
                source_space = KnowledgeSource.space_id == space_id if space_id else True
            else:
                source_space = KnowledgeSource.space_id.in_(requested_space_ids)
            hot_results: list[dict[str, Any]] = []
            if session_id:
                state = await db.scalar(
                    select(ConversationState)
                    .join(ChatSession, ConversationState.session_id == ChatSession.id)
                    .where(
                        ConversationState.session_id == session_id,
                        ChatSession.user_id == user_id,
                        ChatSession.tenant_id == tenant,
                        ChatSession.workspace_id == workspace,
                    )
                )
                for item in (
                    (getattr(state, "last_results", None) or []) if state is not None else []
                ):
                    if not isinstance(item, dict) or not str(
                        item.get("source_type", "")
                    ).startswith("knowledge"):
                        continue
                    body = str(item.get("text") or item.get("summary") or "")
                    title = str(item.get("title") or "Knowledge")
                    if any(token in f"{title} {body}".lower() for token in tokens):
                        hot_results.append(
                            {
                                **item,
                                "source_type": item.get("source_type", "knowledge_page"),
                                "score": max(float(item.get("score", 0.0) or 0.0), 0.95),
                                "evidence_tier": "hot",
                                "disclosure_stage": "hot",
                                "provenance": {
                                    **(item.get("provenance") or {}),
                                    "session_id": session_id,
                                },
                            }
                        )
            if access_context is not None and hot_results:
                hot_source_ids = {
                    str(item.get("source_id") or (item.get("provenance") or {}).get("source_id"))
                    for item in hot_results
                    if item.get("source_id") or (item.get("provenance") or {}).get("source_id")
                }
                allowed_hot_source_ids = set(
                    (
                        await db.execute(
                            select(KnowledgeSource.id).where(
                                KnowledgeSource.id.in_(hot_source_ids),
                                source_access,
                                source_space,
                            )
                        )
                    ).scalars()
                )
                hot_results = [
                    item
                    for item in hot_results
                    if str(item.get("source_id") or (item.get("provenance") or {}).get("source_id"))
                    in allowed_hot_source_ids
                ]
            page_stmt = (
                select(KnowledgePage, KnowledgeSource, KnowledgeSourceVersion)
                .join(
                    KnowledgeSourceVersion,
                    KnowledgePage.source_version_id == KnowledgeSourceVersion.id,
                )
                .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
                .where(
                    KnowledgePage.tenant_id == tenant,
                    KnowledgePage.workspace_id == workspace,
                    KnowledgePage.status == "published",
                    KnowledgeSource.status == "published",
                    KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
                    source_space,
                )
            )
            if source_access is not None:
                page_stmt = page_stmt.where(source_access)
            else:
                owner_clause = _owner_filter(KnowledgePage.owner_id, user_id)
                if owner_clause is not None:
                    page_stmt = page_stmt.where(owner_clause)
                if project_id:
                    page_stmt = page_stmt.where(KnowledgeSource.project_id == project_id)
            page_filters: list[Any] = []
            for token in tokens:
                like = f"%{token}%"
                page_filters.extend(
                    (KnowledgePage.title.ilike(like), KnowledgePage.content.ilike(like))
                )
            page_search = func.to_tsvector(
                "simple", func.concat(KnowledgePage.title, " ", KnowledgePage.content)
            )
            page_query = func.plainto_tsquery("simple", query)
            rows = (
                await db.execute(
                    page_stmt.where(or_(or_(*page_filters), page_search.op("@@")(page_query)))
                    .order_by(func.ts_rank_cd(page_search, page_query).desc())
                    .limit(max(top_k * 4, 20))
                )
            ).all()

            claim_stmt = (
                select(KnowledgeClaim, KnowledgePage, KnowledgeSource, KnowledgeSourceVersion)
                .join(KnowledgePage, KnowledgeClaim.page_id == KnowledgePage.id)
                .join(
                    KnowledgeSourceVersion,
                    KnowledgeClaim.source_version_id == KnowledgeSourceVersion.id,
                )
                .join(KnowledgeSource, KnowledgeSourceVersion.source_id == KnowledgeSource.id)
                .where(
                    KnowledgeClaim.tenant_id == tenant,
                    KnowledgeClaim.workspace_id == workspace,
                    KnowledgeClaim.status == "published",
                    KnowledgePage.status == "published",
                    KnowledgeSource.status == "published",
                    KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
                    source_space,
                )
            )
            if source_access is not None:
                claim_stmt = claim_stmt.where(source_access)
            else:
                owner_clause = _owner_filter(KnowledgeClaim.owner_id, user_id)
                if owner_clause is not None:
                    claim_stmt = claim_stmt.where(owner_clause)
                if project_id:
                    claim_stmt = claim_stmt.where(KnowledgeSource.project_id == project_id)
            claim_filters = [KnowledgeClaim.text.ilike(f"%{token}%") for token in tokens]
            claim_search = func.to_tsvector(
                "simple", func.concat(KnowledgeClaim.text, " ", KnowledgeClaim.normalized_text)
            )
            claim_query = func.plainto_tsquery("simple", query)
            claim_rows = (
                await db.execute(
                    claim_stmt.where(or_(or_(*claim_filters), claim_search.op("@@")(claim_query)))
                    .order_by(func.ts_rank_cd(claim_search, claim_query).desc())
                    .limit(max(top_k * 5, 24))
                )
            ).all()

            relation_rows = []
            effective_query_type = query_type or infer_knowledge_query_type(query)
            relation_query = effective_query_type in {"relation", "comparison"} or any(
                marker in (query or "") for marker in ("关系", "区别", "对比", "关联", "依赖")
            )
            if relation_query:
                # SQLAlchemy needs explicit aliases for the two page ends.
                from sqlalchemy.orm import aliased

                source_page = aliased(KnowledgePage)
                target_page = aliased(KnowledgePage)
                relation_stmt = (
                    select(KnowledgeRelation, source_page, target_page, KnowledgeSource)
                    .join(source_page, KnowledgeRelation.source_page_id == source_page.id)
                    .join(target_page, KnowledgeRelation.target_page_id == target_page.id)
                    .join(
                        KnowledgeSourceVersion,
                        KnowledgeRelation.source_version_id == KnowledgeSourceVersion.id,
                    )
                    .join(
                        KnowledgeSource,
                        KnowledgeSourceVersion.source_id == KnowledgeSource.id,
                    )
                    .where(
                        KnowledgeRelation.tenant_id == tenant,
                        KnowledgeRelation.workspace_id == workspace,
                        KnowledgeRelation.status == "published",
                        source_page.status == "published",
                        target_page.status == "published",
                        KnowledgeSource.status == "published",
                        KnowledgeSource.active_version_id == KnowledgeSourceVersion.id,
                        source_space,
                    )
                )
                relation_filters: list[Any] = []
                for token in tokens:
                    like = f"%{token}%"
                    relation_filters.extend(
                        (
                            source_page.title.ilike(like),
                            source_page.content.ilike(like),
                            target_page.title.ilike(like),
                            target_page.content.ilike(like),
                        )
                    )
                if source_access is not None:
                    relation_stmt = relation_stmt.where(source_access)
                else:
                    owner_clause = _owner_filter(source_page.owner_id, user_id)
                    if owner_clause is not None:
                        relation_stmt = relation_stmt.where(
                            owner_clause,
                            target_page.owner_id == user_id,
                        )
                    if project_id:
                        relation_stmt = relation_stmt.where(
                            KnowledgeSource.project_id == project_id
                        )
                relation_rows = (
                    await db.execute(
                        relation_stmt.where(or_(*relation_filters)).limit(max(top_k * 3, 12))
                    )
                ).all()
                max_hops = build_knowledge_query_plan(effective_query_type, top_k).max_hops
                if max_hops > 1:
                    # Expand a bounded graph around pages already matched by
                    # lexical/FTS retrieval.  This is intentionally bounded
                    # by candidate budget to avoid untrusted graph traversal.
                    anchor_ids = {page.id for page, _, _ in rows}
                    anchor_ids.update(page.id for _, page, _, _ in claim_rows)
                    graph_rows = (
                        await db.execute(
                            relation_stmt.order_by(KnowledgeRelation.confidence.desc()).limit(
                                max(
                                    int(getattr(settings, "knowledge_query_candidate_budget", 60)),
                                    top_k * 6,
                                )
                            )
                        )
                    ).all()
                    frontier = set(anchor_ids)
                    visited = set(anchor_ids)
                    expanded = list(relation_rows)
                    for _ in range(max_hops):
                        next_frontier: set[str] = set()
                        for candidate in graph_rows:
                            relation, source_page, target_page, _source = candidate
                            if source_page.id in frontier or target_page.id in frontier:
                                if candidate not in expanded:
                                    expanded.append(candidate)
                                for page_id in (source_page.id, target_page.id):
                                    if page_id not in visited:
                                        visited.add(page_id)
                                        next_frontier.add(page_id)
                        if not next_frontier:
                            break
                        frontier = next_frontier
                    relation_rows = expanded[: max(top_k * 4, 16)]
    except SQLAlchemyError as exc:
        # 未迁移环境保留原始文档兜底，但必须留下可观测错误，禁止静默吞掉授权查询失败。
        logger.warning("knowledge_query_unavailable", error=str(exc))
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hot in hot_results:
        key = f"{hot.get('source_type')}:{hot.get('id')}"
        if key not in seen:
            seen.add(key)
            results.append(hot)
    for page, source, version in rows:
        score = _score(page.content, page.title, tokens, query=query)
        if score <= 0:
            continue
        key = f"page:{page.id}"
        seen.add(key)
        results.append(
            {
                "id": page.id,
                "source_type": "knowledge_page",
                "title": page.title,
                "text": page.summary or page.content[:900],
                "score": _governed_score(score, source, page.authority),
                "knowledge_page_id": page.id,
                "source_id": source.id,
                "source_version_id": version.id,
                "document_id": source.document_id,
                "authority": page.authority,
                "knowledge_status": page.status,
                "evidence_tier": "factual",
                "disclosure_stage": "summary",
                **_source_governance(source),
                "provenance": {
                    "source_id": source.id,
                    "source_version_id": version.id,
                    "document_id": source.document_id,
                },
            }
        )
    for claim, page, source, version in claim_rows:
        key = f"claim:{claim.id}"
        if key in seen:
            continue
        score = _score(claim.text, page.title, tokens, query=query)
        if score <= 0:
            continue
        results.append(
            {
                "id": claim.id,
                "source_type": "knowledge_claim",
                "title": page.title,
                "text": claim.text,
                "score": _governed_score(
                    min(0.99, score + claim.confidence * 0.12), source, claim.authority
                ),
                "knowledge_page_id": page.id,
                "claim_id": claim.id,
                "source_id": source.id,
                "source_version_id": version.id,
                "document_id": source.document_id,
                "chunk_id": claim.evidence_chunk_id,
                "evidence_start": claim.evidence_start,
                "evidence_end": claim.evidence_end,
                "authority": claim.authority,
                "knowledge_status": claim.status,
                "evidence_tier": "factual",
                "disclosure_stage": "claim",
                **_source_governance(source),
                "provenance": {
                    "source_id": source.id,
                    "source_version_id": version.id,
                    "document_id": source.document_id,
                    "evidence_chunk_id": claim.evidence_chunk_id,
                    "evidence_start": claim.evidence_start,
                    "evidence_end": claim.evidence_end,
                },
            }
        )
    for relation, source_page, target_page, source in relation_rows:
        relation_text = f"{source_page.title} {relation.relation_type} {target_page.title}"
        source_meta = source_page.page_metadata or {}
        target_meta = target_page.page_metadata or {}
        results.append(
            {
                "id": relation.id,
                "source_type": "knowledge_relation",
                "title": relation_text,
                "text": relation_text,
                "score": _governed_score(
                    min(0.99, 0.55 + relation.confidence * 0.25),
                    source,
                    relation.authority,
                ),
                "knowledge_page_id": source_page.id,
                "relation_id": relation.id,
                "target_page_id": target_page.id,
                "document_id": source.document_id,
                "relation_type": relation.relation_type,
                "source_id": source.id,
                "source_version_id": relation.source_version_id,
                "authority": relation.authority,
                "knowledge_status": relation.status,
                "evidence_tier": "structural",
                "disclosure_stage": "relation",
                **_source_governance(source),
                "provenance": {
                    "relation_id": relation.id,
                    "source_page_id": source_page.id,
                    "target_page_id": target_page.id,
                    "source_version_id": relation.source_version_id,
                    "source_document_id": source_meta.get("document_id") or source.document_id,
                    "target_document_id": target_meta.get("document_id"),
                },
            }
        )
    results.sort(key=lambda item: float(item["score"]), reverse=True)
    return results[: max(1, top_k)]
