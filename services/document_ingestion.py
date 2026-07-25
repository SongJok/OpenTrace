"""共享文档分块、Embedding 与持久化摄入服务。"""

from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from infra.observability.logger import get_logger
from infra.storage.models import Document, DocumentChunk, DocumentLLMWiki

logger = get_logger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNK_MAX_CHARS = 800
CHUNK_MIN_CHARS = 80


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = re.sub(r"\u0000", "", text)
    text = text.replace("\ufffd", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Context-aware chunking (Strategy 1) ───────────────────────────────────────

# Chinese / multilingual sentence boundary punctuation.
_CJK_SENTENCE_END = set("。！？；….\n!?;")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, respecting Chinese and Latin punctuation.

    This is a rule-based splitter that preserves the trailing punctuation
    with each sentence and handles multi-line boundaries.
    """
    sentences: list[str] = []
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _CJK_SENTENCE_END:
            # Handle ellipsis (…) and repeated punctuation (！！！)
            while i + 1 < len(text) and text[i + 1] == ch:
                i += 1
            # Skip whitespace after sentence boundary
            end = i + 1
            while end < len(text) and text[end] in " \t":
                end += 1
            seg = text[start:end].strip()
            if seg:
                sentences.append(seg)
            start = end
            i = end
        elif ch == "\n":
            # Newlines can act as sentence boundaries for list-like content
            end = i + 1
            while end < len(text) and text[end] in " \t":
                end += 1
            seg = text[start:i].strip()
            if seg:
                sentences.append(seg)
            start = end
            i = end
        else:
            i += 1

    # Remaining text after last boundary
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)

    return sentences


def _extract_headings(text: str) -> list[tuple[int, int, str]]:
    """Extract markdown headings as (char_start, char_end, heading_text)."""
    headings: list[tuple[int, int, str]] = []
    for m in _HEADING_RE.finditer(text):
        headings.append((m.start(), m.end(), m.group(2).strip()))
    return headings


def _get_heading_at_pos(headings: list[tuple[int, int, str]], pos: int) -> str | None:
    """Return the most recent heading text that covers the given character position."""
    current = None
    for hs, he, ht in headings:
        if hs <= pos:
            current = ht
        else:
            break
    return current


def _context_aware_chunk(text: str, doc_title: str = "") -> list[dict]:
    """Chunk text by semantic boundaries instead of fixed character count.

    Strategy:
    1. Extract markdown headings for section inheritance.
    2. Split text into sentences.
    3. Group consecutive sentences into chunks, flushing when:
       - A new heading-level paragraph starts
       - The accumulated text exceeds CHUNK_MAX_CHARS
       - A topic-shift indicator is detected
    """
    headings = _extract_headings(text)
    sentences = _split_sentences(text)
    if not sentences:
        return []

    # Build a map: sentence_index -> heading (if the sentence starts under a heading)
    # We approximate by finding where each sentence starts in the original text.
    chunks: list[dict] = []
    current_sentences: list[str] = []
    current_chars = 0
    current_heading: str | None = _get_heading_at_pos(headings, 0)

    def flush_chunk() -> None:
        nonlocal current_sentences, current_chars
        if not current_sentences:
            return
        content = "\n".join(current_sentences)
        heading = _get_heading_at_pos(headings, _find_sentence_start(text, current_sentences[0]))
        chunks.append(
            {
                "content": content,
                "heading": heading or doc_title or "",
                "sentence_count": len(current_sentences),
                "char_count": current_chars,
            }
        )
        current_sentences = []
        current_chars = 0

    for sent in sentences:
        sent_len = len(sent)
        # Flush if a new section heading starts mid-stream, or chunk is too large
        sent_heading = _get_heading_at_pos(headings, _find_sentence_start(text, sent))
        heading_changed = (
            sent_heading != current_heading
            and current_heading is not None
            and sent_heading is not None
        )

        if current_chars > 0 and (
            (current_chars + sent_len > CHUNK_MAX_CHARS)
            or (current_chars >= CHUNK_MIN_CHARS and heading_changed)
        ):
            flush_chunk()
            current_heading = sent_heading

        current_sentences.append(sent)
        current_chars += sent_len

    flush_chunk()

    # Fallback: if context-aware produced too few or too many chunks,
    # split oversized chunks at fixed boundaries as a safety net.
    result: list[dict] = []
    for ch in chunks:
        if ch["char_count"] > CHUNK_MAX_CHARS * 2:
            sub = _split_chunks(ch["content"])
            for sub_text in sub:
                result.append(
                    {
                        "content": sub_text,
                        "heading": ch["heading"],
                        "sentence_count": -1,  # indicates sub-split
                        "char_count": len(sub_text),
                    }
                )
        else:
            result.append(ch)

    return result


def _find_sentence_start(text: str, sentence: str) -> int:
    """Find the character position of a sentence within the full text."""
    idx = text.find(sentence)
    return idx if idx >= 0 else 0


def _split_chunks(text: str, strategy: int = 1, doc_title: str = "") -> list[dict]:
    """Dispatch chunking based on strategy.

    Strategy 1 (default): context-aware — groups sentences by semantic boundaries.
    Strategy 2-8: reserved (fall back to fixed-length for now).
    """
    if strategy == 1:
        return _context_aware_chunk(text, doc_title=doc_title)

    # Fallback: fixed-length chunking returns dicts with compatible keys.
    raw_chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunk = text[start:end].strip()
        if chunk:
            raw_chunks.append(chunk)
        if end >= len(text):
            break
        start += CHUNK_SIZE - CHUNK_OVERLAP

    return [
        {
            "content": c,
            "heading": doc_title or "",
            "sentence_count": -1,
            "char_count": len(c),
        }
        for c in raw_chunks
    ]


async def _embed_chunks(chunks: list[str]) -> list[list[float]]:
    from infra.config.settings import settings
    from model.embedding.base import get_embedder, normalize_embedding_vector

    vectors = await get_embedder().embed(chunks)
    return [normalize_embedding_vector(vec, settings.embedding_dims) for vec in vectors]


def _cosine_score(a: list[float], b: list[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _has_column(db: AsyncSession, table: str, column: str) -> bool:
    result = await db.execute(
        text("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """),
        {"table_name": table, "column_name": column},
    )
    return result.scalar_one_or_none() is not None


async def has_table(db: AsyncSession, table: str) -> bool:
    result = await db.execute(
        text("""
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = :table_name
            LIMIT 1
            """),
        {"table_name": table},
    )
    return result.scalar_one_or_none() is not None


# ── Ingest pipeline ───────────────────────────────────────────────────────────


def merge_ingest_metadata(
    raw_metadata: str | None,
    normalized_metadata: dict,
    project_id: str | None,
) -> dict:
    """标准化摄入元数据，同时保留发布策略等编排命令。"""
    try:
        existing_metadata = json.loads(raw_metadata or "{}")
        if not isinstance(existing_metadata, dict):
            existing_metadata = {}
    except (TypeError, json.JSONDecodeError):
        existing_metadata = {}
    return {
        **normalized_metadata,
        **existing_metadata,
        "project_id": project_id,
    }


async def ingest_document(db: AsyncSession, doc: Document, text: str) -> None:
    from infra.metadata.unified_metadata import make_doc_metadata

    try:
        text = sanitize_text(text)
        doc.status = "processing"
        doc.content = text[:65535]
        # 发布策略属于编排命令的一部分，摄入元数据标准化时不能丢失。
        doc.doc_metadata = json.dumps(
            merge_ingest_metadata(
                doc.doc_metadata,
                make_doc_metadata(owner=doc.owner_id).to_dict(),
                doc.project_id,
            ),
            ensure_ascii=False,
        )
        await db.commit()

        strategy = getattr(doc, "chunk_strategy", 1) or 1
        chunk_dicts = _split_chunks(text, strategy=strategy, doc_title=doc.title)
        if not chunk_dicts:
            doc.status = "error"
            await db.commit()
            return

        chunk_texts = [c["content"] for c in chunk_dicts]
        embeddings = await _embed_chunks(chunk_texts)
        if len(embeddings) != len(chunk_texts):
            from infra.config.settings import settings
            from model.embedding.base import HashEmbedder, normalize_embedding_vector

            fallback = HashEmbedder(dims=settings.embedding_dims)
            embeddings = [
                normalize_embedding_vector(vec, settings.embedding_dims)
                for vec in await fallback.embed(chunk_texts)
            ]

        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        if await has_table(db, "document_llmwiki"):
            await db.execute(delete(DocumentLLMWiki).where(DocumentLLMWiki.document_id == doc.id))

        embedding_vector_supported = await _has_column(db, "document_chunks", "embedding_vector")

        for idx, (chunk_dict, emb) in enumerate(zip(chunk_dicts, embeddings)):
            heading = chunk_dict.get("heading", "")
            sentence_count = chunk_dict.get("sentence_count", -1)
            char_count = chunk_dict.get("char_count", len(chunk_dict["content"]))
            chunk_meta = {
                "heading": heading,
                "sentence_count": sentence_count,
                "char_count": char_count,
                "strategy": strategy,
                "metadata": make_doc_metadata(
                    owner=doc.owner_id, tags=["chunk", f"doc:{doc.id}"]
                ).to_dict(),
            }
            chunk_kwargs = dict(
                id=str(uuid.uuid4()),
                document_id=doc.id,
                chunk_index=idx,
                content=chunk_dict["content"],
                embedding_json=json.dumps(emb),
                embedding_dims=len(emb),
                chunk_metadata=json.dumps(chunk_meta),
            )
            if embedding_vector_supported:
                chunk_kwargs["embedding_vector"] = emb
            db.add(DocumentChunk(**chunk_kwargs))

        doc.chunk_count = len(chunk_dicts)
        doc.status = "ready"
        await db.commit()
        logger.info("Document ingested", doc_id=doc.id, chunks=len(chunk_dicts), strategy=strategy)
    except Exception as exc:
        doc.status = "error"
        try:
            await db.commit()
        except Exception as commit_exc:
            logger.warning("document_error_status_commit_failed", error=str(commit_exc))
        logger.error("Document ingest failed", doc_id=doc.id, error=str(exc))
        raise
