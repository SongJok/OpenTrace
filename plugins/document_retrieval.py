"""Shared document retrieval helpers for RAG and document search."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from sqlalchemy import or_, select

from infra.config.settings import settings
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import Document, DocumentChunk
from model.embedding.base import get_embedder, normalize_embedding_vector


@dataclass(slots=True)
class DocumentCandidate:
    chunk: DocumentChunk
    title: str


@dataclass(slots=True)
class ScoredDocumentChunk:
    chunk: DocumentChunk
    title: str
    score: float


@dataclass(slots=True)
class DocumentEvidenceGate:
    min_score: float = 0.35
    min_gap: float = 0.05

    def passes(self, scored: list[ScoredDocumentChunk]) -> bool:
        if not scored:
            return False
        best = scored[0].score
        second = scored[1].score if len(scored) > 1 else 0.0
        return best >= self.min_score or (best - second) >= self.min_gap


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", (text or "").lower())


def cosine_score(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def build_query_embedding(query: str) -> list[float]:
    vec = (await get_embedder().embed([query]))[0]
    return normalize_embedding_vector(vec, settings.embedding_dims)


def _document_owner_clause(user_id: str):
    """Restrict retrieval to documents owned by the requesting user."""
    uid = (user_id or "").strip()
    if not uid or uid == "shared":
        return None
    return Document.owner_id == uid


def _document_tenant_clause(tenant_id: str | None, workspace_id: str | None):
    """Filter by documents.tenant_id / workspace_id columns (equality)."""
    from sqlalchemy import and_

    tid = (tenant_id or "").strip() or "default"
    wid = (workspace_id or "").strip() or "default"
    return and_(Document.tenant_id == tid, Document.workspace_id == wid)


def _apply_document_scope(stmt, *, user_id: str, tenant_id: str | None = None, workspace_id: str | None = None):
    owner = _document_owner_clause(user_id)
    if owner is not None:
        stmt = stmt.where(owner)
    tenant = _document_tenant_clause(tenant_id, workspace_id)
    if tenant is not None:
        stmt = stmt.where(tenant)
    return stmt


async def fetch_document_candidates(
    user_id: str,
    query: str,
    limit: int = 200,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> list[DocumentCandidate]:
    candidates = await _fetch_document_candidates_vector(
        user_id=user_id,
        query=query,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if candidates:
        return candidates

    terms = tokenize(query)
    async with AsyncSessionLocal() as db:
        stmt = (
            select(DocumentChunk, Document.title)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.status == "ready")
        )
        stmt = _apply_document_scope(
            stmt,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if terms:
            filters = []
            for term in terms[:8]:
                like = f"%{term}%"
                filters.append(Document.title.ilike(like))
                filters.append(DocumentChunk.content.ilike(like))
            stmt = stmt.where(or_(*filters))
        stmt = stmt.order_by(Document.updated_at.desc()).limit(limit)
        result = await db.execute(stmt)
        rows = result.all()

    return [DocumentCandidate(chunk=chunk, title=title or "Document") for chunk, title in rows]


async def score_document_candidates(
    query: str, candidates: list[DocumentCandidate], query_type: str = "general"
) -> list[ScoredDocumentChunk]:
    if not candidates:
        return []

    query_terms = tokenize(query)
    query_embedding: list[float] | None = None
    try:
        query_embedding = await build_query_embedding(query)
    except Exception:
        query_embedding = None

    # Query-type-aware vector vs lexical weights
    type_weights = {
        "definition": (0.80, 0.20),  # rely more on semantic similarity
        "fact": (0.50, 0.50),
        "procedure": (0.40, 0.60),  # steps/actions match better via keywords
        "comparison": (0.55, 0.45),
        "general": (0.75, 0.25),
    }
    vw, lw = type_weights.get(query_type, type_weights["general"])

    scored: list[ScoredDocumentChunk] = []
    for candidate in candidates:
        chunk = candidate.chunk
        title = candidate.title
        emb_json = getattr(chunk, "embedding_json", None)
        lexical_score = lexical_overlap_score(f"{title or ''}\n{chunk.content or ''}", query_terms)

        vector_score = 0.0
        if emb_json and query_embedding is not None:
            try:
                emb = normalize_embedding_vector(json.loads(emb_json), settings.embedding_dims)
                vector_score = cosine_score(query_embedding, emb)
            except Exception:
                vector_score = 0.0

        score = max(vector_score, lexical_score * 0.92, (vector_score * vw) + (lexical_score * lw), lexical_score * 0.65)
        score += title_boost(title, query_terms)
        score = apply_rerank_boost(score, query_terms, title, chunk.content or "")

        # If embeddings are missing, keep lexical-only chunks instead of dropping them.
        if vector_score <= 0.0 and lexical_score <= 0.0:
            continue

        scored.append(ScoredDocumentChunk(chunk=chunk, title=title, score=min(score, 0.999)))

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def lexical_overlap_score(text: str, query_terms: list[str]) -> float:
    text_l = (text or "").lower()
    if not query_terms or not text_l:
        return 0.0
    hit = sum(1 for term in query_terms if term and term in text_l)
    return hit / max(1, len(query_terms))


def title_boost(title: str, query_terms: list[str]) -> float:
    title_l = (title or "").lower()
    if not title_l or not query_terms:
        return 0.0
    query_text = " ".join(query_terms)
    if query_text and (query_text in title_l or title_l in query_text):
        return 0.18
    return 0.08 if any(term in title_l for term in query_terms) else 0.0


def apply_rerank_boost(score: float, query_terms: list[str], title: str, content: str) -> float:
    text_l = f"{title or ''}\n{content or ''}".lower()
    if not query_terms or not text_l:
        return score
    overlap = sum(1 for term in query_terms if term in text_l)
    if overlap == 0:
        return score * 0.95

    # Proportional bonus: more terms matched → higher boost (up to 0.10)
    ratio = overlap / max(1, len(query_terms))
    proportional_bonus = min(0.10, ratio * 0.12)

    # Phrase bonus: 2+ consecutive query terms appearing in order
    phrase_bonus = 0.0
    if len(query_terms) >= 2:
        for i in range(len(query_terms) - 1):
            phrase = " ".join(query_terms[i : i + 2])
            if phrase in text_l:
                phrase_bonus = 0.08
                break

    # Position bonus: terms in the first 20% of content
    position_bonus = 0.0
    content_l = (content or "").lower()
    if content_l and any(term in content_l[: max(1, len(content_l) // 5)] for term in query_terms[:4]):
        position_bonus = 0.05

    return min(0.999, score + proportional_bonus + phrase_bonus + position_bonus)


async def _fetch_document_candidates_vector(
    user_id: str,
    query: str,
    limit: int,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> list[DocumentCandidate]:
    if not getattr(settings, "use_pgvector", True):
        return []

    try:
        query_embedding = await build_query_embedding(query)
        async with AsyncSessionLocal() as db:
            stmt = (
                select(DocumentChunk, Document.title)
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(Document.status == "ready")
            )
            stmt = _apply_document_scope(
                stmt,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            stmt = stmt.order_by(DocumentChunk.embedding_vector.l2_distance(query_embedding)).limit(limit)
            result = await db.execute(stmt)
            rows = result.all()

            if not rows:
                stmt = (
                    select(DocumentChunk, Document.title)
                    .join(Document, DocumentChunk.document_id == Document.id)
                    .where(Document.status == "ready")
                    .where(DocumentChunk.embedding_json.is_not(None))
                )
                stmt = _apply_document_scope(
                    stmt,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
                stmt = stmt.limit(limit)
                result = await db.execute(stmt)
                rows = result.all()
        return [DocumentCandidate(chunk=chunk, title=title or "Document") for chunk, title in rows]
    except Exception:
        return []


async def fetch_document_candidates_fallback(
    user_id: str,
    query: str,
    limit: int = 200,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> list[DocumentCandidate]:
    terms = tokenize(query)
    async with AsyncSessionLocal() as db:
        stmt = (
            select(DocumentChunk, Document.title)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.status.in_(["ready", "processing", "pending"]))
        )
        stmt = _apply_document_scope(
            stmt,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if terms:
            filters = []
            for term in terms[:8]:
                like = f"%{term}%"
                filters.append(Document.title.ilike(like))
                filters.append(DocumentChunk.content.ilike(like))
            stmt = stmt.where(or_(*filters))
        stmt = stmt.order_by(Document.updated_at.desc()).limit(limit)
        result = await db.execute(stmt)
        rows = result.all()

    return [DocumentCandidate(chunk=chunk, title=title or "Document") for chunk, title in rows]
