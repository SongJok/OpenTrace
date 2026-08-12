"""
DocumentPlugin — 文档认知插件
将文档系统接入 Cognitive Kernel，通过向量检索和 LLMwiki 双路检索用户上传文档。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, or_, select, text

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.security.resource_scope import accessible_document_predicate
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import Document, DocumentChunk, DocumentLLMWiki
from kernel.json_parser import parse_llm_json
from model.embedding.base import get_embedder, normalize_embedding_vector
from model.llm_adapter.base import LLMConfig, LLMMessage
from model.llm_adapter.openai_adapter import OpenAICompatibleAdapter
from plugins.base import BasePlugin, PluginResult
from plugins.document_retrieval import (
    fetch_document_candidates,
    fetch_document_candidates_fallback,
    score_document_candidates,
    tokenize,
)
from plugins.document_retrieval import (
    lexical_overlap_score as _lexical_overlap_score,
)
from plugins.document_retrieval import (
    title_boost as _title_boost,
)

if TYPE_CHECKING:
    from kernel.context_builder import ContextChunk, UnifiedContext

logger = get_logger(__name__)


@dataclass(slots=True)
class LLMWikiEntryDraft:
    chunk_id: str | None
    question: str
    answer: str
    keywords: list[str]
    embedding_json: str | None = None
    embedding_vector: Any = None


# Compatibility wrappers kept for contract tests and readability.
def lexical_overlap_score(text: str, query_terms: list[str]) -> float:
    return _lexical_overlap_score(text, query_terms)


def title_boost(title: str, query_terms: list[str]) -> float:
    return _title_boost(title, query_terms)


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text_value = (raw or "").strip()
    if not text_value:
        return None

    candidates = [text_value]
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text_value, re.IGNORECASE)
    if fence:
        candidates.insert(0, fence.group(1).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    parsed = parse_llm_json(text_value)
    if parsed is None:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_keywords(keywords: Any, fallback_text: str) -> list[str]:
    """增强关键词提取：LLM结果 + 规则兜底，确保业务术语不被遗漏"""
    # 1. 解析LLM返回的keywords
    if isinstance(keywords, list):
        terms = [str(item).strip().lower() for item in keywords if str(item).strip()]
    else:
        terms = []

    # 2. 🔥 规则兜底：从原文提取业务术语
    business_terms = [
        "队长",
        "负责人",
        "组长",
        "管理员",
        "操作员",
        "录入大厅",
        "大厅",
        "准入",
        "资质",
        "资格",
        "认证",
        "账号",
        "账户",
        "权限",
        "角色",
        "身份",
        "资质账号",
        "任务",
        "分发",
        "审核",
        "审批",
        "任务分发",
        "结果审核",
        "定级",
        "等级",
        "级别",
        "职级",
        "初级",
        "中级",
        "高级",
        "L1",
        "L2",
        "L3",
    ]
    for term in business_terms:
        if term in fallback_text.lower():
            terms.append(term.lower())

    # 3. 🔥 提取"X：Y"定义句式中的关键实体
    import re

    definitions = re.findall(r"([^\s：:]+)\s*[:：是指即]\s*([^\n。.!?;；]+)", fallback_text)
    for subject, predicate in definitions:
        subject = subject.strip().lower()
        if subject and len(subject) >= 2:
            terms.append(subject)
        nouns = re.findall(r"[\u4e00-\u9fff]{2,4}|[a-zA-Z]{3,}", predicate)
        for noun in nouns:
            terms.append(noun.lower())

    # 4. 兜底分词
    if not terms:
        terms = tokenize(fallback_text)[:12]

    # 5. 去重+截断
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term and len(term.strip()) >= 2 and term not in seen:
            seen.add(term.strip())
            unique.append(term.strip())

    return unique[:15]


def _fallback_llmwiki_entry(chunk: DocumentChunk, title: str) -> dict[str, Any]:
    body = " ".join((chunk.content or "").split())
    if not body:
        return {
            "question": f"{title or '这份文档'}的这部分主要讲了什么？",
            "answer": "该片段暂无可用摘要。",
            "keywords": [],
        }

    # Extract first definition-pattern sentence for a better question hint
    import re

    def_pattern = re.search(
        r"([^\n。.!?;；]{2,40}?(?:是指|即为|就是|：|:)[^\n。.!?;；]{2,60})", body
    )
    entity_pattern = re.search(
        r"([^\n。.!?;；]{2,30}?(?:队长|负责人|管理员|操作员|角色|权限|资质|账号|任务|流程))", body
    )
    first_sentence = body[:120].rsplit("。", 1)[0] if "。" in body[:120] else body[:120]

    if def_pattern:
        snippet = def_pattern.group(1).strip()
        question = f"关于「{snippet[:30]}」，具体是怎么定义的？"
        answer = snippet[:220]
    elif entity_pattern:
        entity = entity_pattern.group(1).strip()
        question = f"关于「{entity}」，文档中是怎么说明的？"
        answer = body[:220]
    else:
        question = f"{title or '这份文档'}的这部分主要讲了什么？"
        answer = first_sentence[:220] if first_sentence else body[:220]

    keywords = _normalize_keywords([], f"{title}\n{body}")
    return {
        "question": question,
        "answer": answer,
        "keywords": keywords,
    }


async def _has_table(table_name: str) -> bool:
    async with AsyncSessionLocal() as db:
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
            {"table_name": table_name},
        )
        return result.scalar_one_or_none() is not None


def _llmwiki_adapter() -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        LLMConfig(
            provider=settings.default_llm_query_provider,
            model=settings.llmwiki_model or settings.default_llm_query_model,
            base_url=settings.default_llm_query_base_url,
            api_key=settings.default_llm_query_api_key,
            temperature=0.2,
            max_tokens=280,
            timeout=60,
        )
    )


async def _generate_llmwiki_entry_with_llm(
    adapter: OpenAICompatibleAdapter,
    title: str,
    chunk: DocumentChunk,
) -> dict[str, Any]:
    # 🔥 优化 prompt：显式要求生成定义类问答
    prompt = (
        "你是一名企业知识库整理专家。请分析文档片段，生成用户可能提问的问题和答案。\n\n"
        "生成要求:\n"
        '1. [定义优先] 如果片段包含定义句式(如"队长：录入大厅账号")，优先生成"什么是队长？"类型问题\n'
        "2. [答案简洁] answer 必须包含核心定义，≤80字，保留关键业务术语\n"
        "3. [关键词完整] keywords 必须包含：实体名+属性+场景词+同义词\n"
        "4. [业务术语] 特别关注：录入大厅/资质/账号/队长/负责人/任务/审核/定级等词汇\n\n"
        "输出格式(严格JSON):\n"
        '{"question":"...","answer":"...","keywords":["实体","属性","场景","同义词"]}\n\n'
        f"文档标题：{title or '未命名文档'}\n"
        f"片段内容：\n{(chunk.content or '')[:1600]}"
    )
    try:
        response = await adapter.complete(
            [
                LLMMessage(role="system", content="你是一个企业知识库整理助手，只输出合法 JSON。"),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.2,
            max_tokens=280,
        )
        parsed = _extract_json_object(response.content)
        if not parsed:
            return _fallback_llmwiki_entry(chunk, title)
        question = str(parsed.get("question") or "").strip()
        answer = str(parsed.get("answer") or "").strip()
        fallback = _fallback_llmwiki_entry(chunk, title)
        return {
            "question": question or fallback["question"],
            "answer": answer or fallback["answer"],
            "keywords": _normalize_keywords(
                parsed.get("keywords"), f"{title}\n{chunk.content or ''}"
            ),
        }
    except Exception as exc:
        logger.warning(
            "LLMwiki generation failed; using fallback summary", error=str(exc), chunk_id=chunk.id
        )
        return _fallback_llmwiki_entry(chunk, title)


async def _build_llmwiki_drafts(title: str, chunks: list[DocumentChunk]) -> list[LLMWikiEntryDraft]:
    if not chunks:
        return []

    adapter = _llmwiki_adapter()
    drafts: list[LLMWikiEntryDraft] = []
    payloads: list[dict[str, Any]] = []
    for chunk in chunks:
        payloads.append(await _generate_llmwiki_entry_with_llm(adapter, title, chunk))

    embedding_inputs = [
        f"{payload.get('question', '')}\n{payload.get('answer', '')}".strip()
        for payload in payloads
    ]
    embeddings: list[list[float] | None] = [None] * len(embedding_inputs)
    try:
        raw_vectors = await get_embedder().embed(embedding_inputs, input_type="document")
        embeddings = [
            (
                normalize_embedding_vector(vec, settings.embedding_dims)
                if isinstance(vec, list)
                else None
            )
            for vec in raw_vectors
        ]
    except Exception as exc:
        logger.warning("LLMwiki embedding generation skipped", error=str(exc))

    for chunk, payload, embedding in zip(chunks, payloads, embeddings):
        drafts.append(
            LLMWikiEntryDraft(
                chunk_id=chunk.id,
                question=str(payload.get("question") or "").strip(),
                answer=str(payload.get("answer") or "").strip(),
                keywords=_normalize_keywords(
                    payload.get("keywords"), f"{title}\n{chunk.content or ''}"
                ),
                embedding_json=json.dumps(embedding) if embedding else None,
                embedding_vector=None,
            )
        )
    return drafts


async def generate_llmwiki_entries(document_id: str) -> int:
    if not settings.llmwiki_enabled:
        return 0
    if not await _has_table("document_llmwiki"):
        logger.info("LLMwiki table not available; skipping generation", document_id=document_id)
        return 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == document_id).limit(1))
        document = result.scalar_one_or_none()
        if not document or document.status != "ready":
            return 0

        chunk_rows = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        chunks = chunk_rows.scalars().all()

        # 生成过程可能包含模型与嵌入调用，不在此期间持有数据库锁。
        await db.commit()

        drafts = await _build_llmwiki_drafts(document.title, chunks)
        # 删除文档与衍生内容发布共用事务级 advisory lock。删除若先完成，
        # 这里会在重检时安全退出；发布若先完成，删除会等待并级联清理。
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:document_id))"),
            {"document_id": document_id},
        )
        current = await db.scalar(
            select(Document)
            .where(Document.id == document_id, Document.status == "ready")
            .with_for_update()
        )
        if current is None:
            await db.rollback()
            return 0
        chunk_ids = set(
            (
                await db.execute(
                    select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
                )
            )
            .scalars()
            .all()
        )
        valid_drafts = [draft for draft in drafts if draft.chunk_id in chunk_ids]
        await db.execute(delete(DocumentLLMWiki).where(DocumentLLMWiki.document_id == document_id))
        for draft in valid_drafts:
            db.add(
                DocumentLLMWiki(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    chunk_id=draft.chunk_id,
                    question=draft.question,
                    answer=draft.answer,
                    keywords=draft.keywords,
                    embedding_json=draft.embedding_json,
                    embedding_dims=settings.embedding_dims,
                    embedding_vector=draft.embedding_vector,
                )
            )

        await db.commit()
        logger.info("LLMwiki entries generated", document_id=document_id, count=len(valid_drafts))
        return len(valid_drafts)


class DocumentPlugin(BasePlugin):
    name = "document"
    description = "从用户上传的文档中检索相关内容"

    async def execute(self, query: str, context: UnifiedContext) -> PluginResult:
        t0 = time.monotonic()
        user_id = context.metadata.get("user_id", "")
        chunks = await self.search_chunks(query=query, user_id=user_id, top_k=5)
        llmwiki_entries = await self.search_llmwiki(
            query=query,
            user_id=user_id,
            top_k=min(3, max(1, settings.llmwiki_top_k)),
        )
        content_parts = [f"[文档片段 {i + 1}] {c.content[:400]}" for i, c in enumerate(chunks)]
        content_parts.extend(
            f"[LLMWiki {i + 1}] {entry.metadata.get('question', '摘要')}：{entry.content[:240]}"
            for i, entry in enumerate(llmwiki_entries)
        )
        content = "\n\n".join(content_parts)
        confidence = max(
            [c.confidence for c in chunks] + [c.confidence for c in llmwiki_entries] + [0.0]
        )
        return PluginResult(
            plugin_name=self.name,
            content=content,
            confidence=confidence,
            source_type="document",
            metadata={
                "chunk_count": len(chunks),
                "llmwiki_count": len(llmwiki_entries),
            },
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def search_chunks(
        self,
        query: str,
        user_id: str,
        top_k: int = 6,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[ContextChunk]:
        from kernel.context_builder import ContextChunk

        scope = dict(tenant_id=tenant_id, workspace_id=workspace_id)
        try:
            candidates = await fetch_document_candidates(
                user_id=user_id, query=query, limit=200, **scope
            )
            if not candidates:
                candidates = await fetch_document_candidates_fallback(
                    user_id=user_id, query=query, limit=200, **scope
                )
            scored = await score_document_candidates(query=query, candidates=candidates)
            top = scored[:top_k]
            return [
                ContextChunk(
                    content=item.chunk.content,
                    source_type="document",
                    score=item.score,
                    confidence=max(0.0, min(1.0, (item.score + 1.0) / 2.0)),
                    metadata={
                        "document_id": item.chunk.document_id,
                        "chunk_index": item.chunk.chunk_index,
                        "title": item.title,
                        "document_title": item.title,
                    },
                )
                for item in top
            ]
        except Exception as exc:
            logger.debug("DocumentPlugin.search_chunks failed", error=str(exc))
            return []

    async def search_llmwiki(
        self,
        query: str,
        user_id: str,
        top_k: int = 3,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[ContextChunk]:
        from kernel.context_builder import ContextChunk

        if not settings.llmwiki_enabled:
            return []
        if not await _has_table("document_llmwiki"):
            return []

        terms = tokenize(query)
        query_embedding: list[float] | None = None
        try:
            query_embedding = normalize_embedding_vector(
                await get_embedder().embed_one(query),
                settings.embedding_dims,
            )
        except Exception:
            query_embedding = None

        async with AsyncSessionLocal() as db:
            stmt = (
                select(DocumentLLMWiki, Document.title)
                .join(Document, DocumentLLMWiki.document_id == Document.id)
                .where(Document.status == "ready")
            )
            stmt = stmt.where(
                accessible_document_predicate(
                    user_id=user_id,
                    tenant_metadata={"tenant_id": tenant_id, "workspace_id": workspace_id},
                )
            )
            if terms:
                like_filters = []
                for term in terms[:8]:
                    like = f"%{term}%"
                    like_filters.append(DocumentLLMWiki.question.ilike(like))
                    like_filters.append(DocumentLLMWiki.answer.ilike(like))
                stmt = stmt.where(
                    or_(
                        DocumentLLMWiki.keywords.overlap(terms[:8]),
                        *like_filters,
                    )
                )
            stmt = stmt.order_by(Document.updated_at.desc()).limit(max(top_k * 12, 24))
            rows = (await db.execute(stmt)).all()

        scored: list[tuple[float, ContextChunk]] = []
        for entry, title in rows:
            question = str(entry.question or "").strip()
            answer = str(entry.answer or "").strip()
            text_blob = f"{title or ''}\n{question}\n{answer}"
            keyword_overlap = 0.0
            if terms:
                keyword_hit = sum(1 for term in terms if term in set(entry.keywords or []))
                keyword_overlap = keyword_hit / max(1, len(terms))
            lexical = lexical_overlap_score(text_blob, terms)
            semantic = 0.0
            if query_embedding and getattr(entry, "embedding_json", None):
                try:
                    entry_embedding = normalize_embedding_vector(
                        json.loads(entry.embedding_json),
                        settings.embedding_dims,
                    )
                    dot = sum(x * y for x, y in zip(query_embedding, entry_embedding))
                    semantic = max(0.0, min(1.0, dot))
                except Exception:
                    semantic = 0.0

            # Weighted composite: semantic > keyword > lexical, with fallback chaining
            if semantic >= 0.40:
                composite = (semantic * 0.65) + (keyword_overlap * 0.25) + (lexical * 0.10)
            elif keyword_overlap >= 0.40:
                composite = (keyword_overlap * 0.55) + (semantic * 0.30) + (lexical * 0.15)
            else:
                composite = (semantic * 0.35) + (keyword_overlap * 0.35) + (lexical * 0.30)
            score = max(semantic, keyword_overlap * 0.98, lexical * 0.92, composite)
            score += title_boost(str(title or ""), terms)
            score = min(score, 0.999)
            if score <= 0:
                continue

            scored.append(
                (
                    score,
                    ContextChunk(
                        content=answer,
                        source_type="llmwiki",
                        score=score,
                        confidence=max(0.0, min(1.0, score + 0.08)),
                        metadata={
                            "document_id": entry.document_id,
                            "chunk_id": entry.chunk_id,
                            "title": title or "Document",
                            "question": question,
                            "keywords": list(entry.keywords or []),
                        },
                    ),
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]
