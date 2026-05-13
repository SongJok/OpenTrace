"""
Documents router — CRUD + semantic search for user documents.
All ingested documents are chunked + embedded and stored via DocumentChunk
for retrieval by DocumentPlugin inside the Cognitive Kernel.

Endpoints:
  GET    /documents              — list user docs
  POST   /documents              — upload + process (multipart)
  GET    /documents/{id}         — document detail
  DELETE /documents/{id}         — delete doc + all chunks
  PUT    /documents/{id}         — re-upload / update title
  POST   /documents/search       — semantic search
"""
from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select, text
from plugins.document_retrieval import fetch_document_candidates, score_document_candidates
from plugins.document_plugin import generate_llmwiki_entries
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.audit.logger import write_audit_log
from infra.errors import AppException, ErrorCodes
from infra.observability.logger import get_logger
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import Document, DocumentChunk, DocumentLLMWiki, User

logger = get_logger(__name__)
router = APIRouter()

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNK_MAX_CHARS = 800  # soft max for context-aware chunks
CHUNK_MIN_CHARS = 80   # minimum sentence group size before flushing


# ── Schemas ───────────────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    title: str
    file_type: str
    file_size: int
    chunk_count: int
    chunk_strategy: int = 1
    version: int
    status: str
    created_at: str
    updated_at: str
    metadata: dict


class DocumentDetail(DocumentOut):
    content_preview: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = 6


class SearchResult(BaseModel):
    document_id: str
    title: str
    chunk_index: int
    content: str
    score: float
    metadata: dict


# ── Text extraction ───────────────────────────────────────────────────────────

def _sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = re.sub(r"\u0000", "", text)
    text = text.replace("\ufffd", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _text_quality_score(text: str) -> float:
    """Simple heuristic: higher means more likely readable natural text."""
    if not text:
        return 0.0
    total = len(text)
    if total == 0:
        return 0.0

    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    alnum = sum(1 for ch in text if ch.isalnum())
    printable = sum(1 for ch in text if ch.isprintable())
    punct = sum(1 for ch in text if ch in "，。！？；：,.!?;:()（）【】[]《》<>-_")

    # Reward printable/alnum/cjk/punctuation ratios, penalize noise characters.
    score = (
        (printable / total) * 0.45
        + (alnum / total) * 0.30
        + (cjk / total) * 0.20
        + (punct / total) * 0.05
    )
    return round(score, 6)


def _decode_text_best_effort(raw: bytes) -> str:
    # Try common encodings for Chinese and UTF text; choose the best quality result.
    candidates: list[str] = []
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5", "latin1"):
        try:
            candidates.append(raw.decode(enc, errors="strict"))
        except Exception:
            continue

    if not candidates:
        candidates.append(raw.decode("utf-8", errors="replace"))

    best = max(candidates, key=_text_quality_score)
    return _sanitize_text(best)


async def _extract_text(raw: bytes, filename: str) -> str:
    fname = filename.lower()

    if fname.endswith(".pdf"):
        pdf_candidates: list[str] = []

        # 1) pypdf
        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(io.BytesIO(raw))
            txt = "\n".join(page.extract_text() or "" for page in reader.pages)
            pdf_candidates.append(_sanitize_text(txt))
        except Exception:
            pass

        # 2) pymupdf (better for many CJK PDFs)
        try:
            import fitz  # type: ignore

            with fitz.open(stream=raw, filetype="pdf") as doc:
                txt = "\n".join(page.get_text("text") or "" for page in doc)
            pdf_candidates.append(_sanitize_text(txt))
        except Exception:
            pass

        # Pick highest quality extracted text.
        pdf_candidates = [c for c in pdf_candidates if c]
        if pdf_candidates:
            best_pdf = max(pdf_candidates, key=_text_quality_score)
            return best_pdf

        # PDF binary content should never be decoded as plain UTF-8 text.
        return ""

    if fname.endswith(".docx"):
        # Prefer python-docx; fallback to unzip xml extraction.
        try:
            import docx  # type: ignore

            document = docx.Document(io.BytesIO(raw))
            parts: list[str] = []
            parts.extend((p.text or "") for p in document.paragraphs)
            for table in document.tables:
                for row in table.rows:
                    cells = [(cell.text or "").strip() for cell in row.cells]
                    row_text = " ".join(cell for cell in cells if cell)
                    if row_text:
                        parts.append(row_text)
            txt = "\n".join(part for part in parts if part.strip())
            return _sanitize_text(txt)
        except Exception:
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    with zf.open("word/document.xml") as f:
                        xml = f.read().decode("utf-8", errors="replace")
                xml = re.sub(r"<[^>]+>", " ", xml)
                xml = re.sub(r"\s+", " ", xml)
                return _sanitize_text(xml)
            except Exception:
                return ""

    return _decode_text_best_effort(raw)


# ── Context-aware chunking (Strategy 1) ───────────────────────────────────────

# Chinese / multilingual sentence boundary punctuation.
_CJK_SENTENCE_END = set('。！？；….\n!?;')
_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)


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
            while end < len(text) and text[end] in ' \t':
                end += 1
            seg = text[start:end].strip()
            if seg:
                sentences.append(seg)
            start = end
            i = end
        elif ch == '\n':
            # Newlines can act as sentence boundaries for list-like content
            end = i + 1
            while end < len(text) and text[end] in ' \t':
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
        chunks.append({
            "content": content,
            "heading": heading or doc_title or "",
            "sentence_count": len(current_sentences),
            "char_count": current_chars,
        })
        current_sentences = []
        current_chars = 0

    for sent in sentences:
        sent_len = len(sent)
        # Flush if a new section heading starts mid-stream, or chunk is too large
        sent_heading = _get_heading_at_pos(headings, _find_sentence_start(text, sent))
        heading_changed = sent_heading != current_heading and current_heading is not None and sent_heading is not None

        if (current_chars > 0 and (
            (current_chars + sent_len > CHUNK_MAX_CHARS)
            or (current_chars >= CHUNK_MIN_CHARS and heading_changed)
        )):
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
                result.append({
                    "content": sub_text,
                    "heading": ch["heading"],
                    "sentence_count": -1,  # indicates sub-split
                    "char_count": len(sub_text),
                })
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
    from model.embedding.base import get_embedder, normalize_embedding_vector
    from infra.config.settings import settings

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
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table, "column_name": column},
    )
    return result.scalar_one_or_none() is not None


async def _has_table(db: AsyncSession, table: str) -> bool:
    result = await db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table},
    )
    return result.scalar_one_or_none() is not None


# ── Ingest pipeline ───────────────────────────────────────────────────────────

async def _ingest(db: AsyncSession, doc: Document, text: str) -> None:
    from infra.metadata.unified_metadata import make_doc_metadata
    try:
        text = _sanitize_text(text)
        doc.status = "processing"
        doc.content = text[:65535]
        doc.doc_metadata = json.dumps(make_doc_metadata(owner=doc.owner_id).to_dict())
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
            from model.embedding.base import HashEmbedder, normalize_embedding_vector
            from infra.config.settings import settings
            fallback = HashEmbedder(dims=settings.embedding_dims)
            embeddings = [normalize_embedding_vector(vec, settings.embedding_dims) for vec in await fallback.embed(chunk_texts)]

        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        if await _has_table(db, "document_llmwiki"):
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
                "metadata": make_doc_metadata(owner=doc.owner_id, tags=["chunk", f"doc:{doc.id}"]).to_dict(),
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
        except Exception:
            pass
        logger.error("Document ingest failed", doc_id=doc.id, error=str(exc))
        raise


def _safe_chunk_meta(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _doc_out(d: Document) -> DocumentOut:
    try:
        meta = json.loads(d.doc_metadata) if d.doc_metadata else {}
    except Exception:
        meta = {}
    return DocumentOut(
        id=d.id,
        title=d.title,
        file_type=d.file_type,
        file_size=d.file_size,
        chunk_count=d.chunk_count,
        chunk_strategy=getattr(d, "chunk_strategy", 1) or 1,
        version=d.version,
        status=d.status,
        created_at=d.created_at.isoformat(),
        updated_at=d.updated_at.isoformat(),
        metadata=meta,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    result = await db.execute(
        select(Document)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_doc_out(d) for d in result.scalars().all()]


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    chunk_strategy: int = Form(1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    raw = await file.read()
    filename = file.filename or "document"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    text = await _extract_text(raw, filename)

    doc = Document(
        id=str(uuid.uuid4()),
        owner_id=current_user.id,
        title=title or filename,
        file_type=ext,
        file_size=len(raw),
        version=1,
        status="pending",
        chunk_strategy=max(1, min(chunk_strategy, 8)),
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    try:
        await _ingest(db, doc, text)
    except Exception as exc:
        await db.rollback()
        doc.status = "error"
        safe_msg = str(exc)[:400]
        try:
            meta = json.loads(doc.doc_metadata) if doc.doc_metadata else {}
        except Exception:
            meta = {}
        meta["last_error"] = safe_msg
        doc.doc_metadata = json.dumps(meta, ensure_ascii=False)
        db.add(doc)
        await db.commit()

    await db.refresh(doc)
    await write_audit_log(
        user_id=current_user.id,
        action="document.upload",
        resource_type="document",
        resource_id=doc.id,
        payload={"title": doc.title, "file_type": doc.file_type, "file_size": doc.file_size, "status": doc.status},
    )
    if doc.status == "ready":
        background_tasks.add_task(generate_llmwiki_entries, doc.id)
    return _doc_out(doc)


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
async def get_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetail:
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Document not found")
    out = _doc_out(doc)
    return DocumentDetail(**out.model_dump(), content_preview=(doc.content or "")[:500])


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Use a narrow existence check first so we do not trigger ORM relationship loading.
    result = await db.execute(
        select(Document.id, Document.title).where(
            Document.id == doc_id,
        )
    )
    row = result.first()
    if not row:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Document not found")

    # Use raw SQL deletes to avoid ORM cascade / lazy-load behavior entirely.
    await db.execute(text("DELETE FROM document_chunks WHERE document_id = :doc_id"), {"doc_id": doc_id})
    await db.execute(text("DELETE FROM documents WHERE id = :doc_id"), {"doc_id": doc_id})
    await db.commit()
    try:
        await write_audit_log(
            user_id=current_user.id,
            action="document.delete",
            resource_type="document",
            resource_id=doc_id,
            payload={"title": row.title},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Document delete audit log failed", doc_id=doc_id, error=str(exc))
    return {"deleted": True, "id": doc_id}


@router.put("/documents/{doc_id}", response_model=DocumentOut)
async def update_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    title: Optional[str] = Form(None),
    chunk_strategy: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Document not found")

    if title:
        doc.title = title
    if chunk_strategy is not None:
        doc.chunk_strategy = max(1, min(chunk_strategy, 8))

    if file:
        raw = await file.read()
        filename = file.filename or "document"
        text = await _extract_text(raw, filename)
        doc.file_size = len(raw)
        doc.version += 1
        await _ingest(db, doc, text)
        if doc.status == "ready":
            background_tasks.add_task(generate_llmwiki_entries, doc.id)
    else:
        await db.commit()

    await db.refresh(doc)
    return _doc_out(doc)


@router.post("/documents/search", response_model=list[SearchResult])
async def search_documents(
    req: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SearchResult]:
    candidates = await fetch_document_candidates(user_id=current_user.id, query=req.query, limit=200)
    scored = await score_document_candidates(query=req.query, candidates=candidates)
    return [
        SearchResult(
            document_id=item.chunk.document_id,
            title=item.title,
            chunk_index=item.chunk.chunk_index,
            content=item.chunk.content,
            score=round(item.score, 4),
            metadata=_safe_chunk_meta(item.chunk.chunk_metadata),
        )
        for item in scored[: req.top_k]
    ]
