from __future__ import annotations

import asyncio
import os
from typing import Any

from sqlalchemy import select

from agents.base import AgentResult, BaseAgent, TaskMessage
from infra.config.settings import settings
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import UserMemory
from kernel.cognitive_controls import (
    _strip_rag_routing_query,
    _substantive_query_terms,
    relevance_score,
)
from knowledge.query import search_knowledge
from model.reranker.base import get_reranker
from plugins.document_plugin import DocumentPlugin
from plugins.document_retrieval import DocumentEvidenceGate, ScoredDocumentChunk
from services.rag_query_planning import (
    assess_answerability,
    build_rag_query_plan,
    build_rag_trace,
    lane_weight,
    normalize_rag_evidence,
)


class RagAgent(BaseAgent):
    """
    RAG 专职 Agent：
    - 文档分块检索（DocumentPlugin）
    - LLMwiki 检索（DocumentPlugin.search_llmwiki）
    - 记忆检索（UserMemory：semantic / episodic）
    - 仅返回证据，不生成最终答案
    """

    @staticmethod
    def _retrieval_query_from_task(task: TaskMessage) -> str:
        """当前轮检索 query：优先 task.query / raw_user_query，仅在多轮已展开时用 resolved。"""
        params = task.params or {}
        raw = str(params.get("raw_user_query", "") or "").strip()
        base = raw or (task.query or "").strip()
        mtr = params.get("multi_turn_resolution")
        if isinstance(mtr, dict) and mtr.get("applied"):
            rq = str(mtr.get("resolved_query", "") or "").strip()
            if rq:
                return rq
        if base:
            return base
        miq = str(params.get("memory_injection_query", "") or "").strip()
        return miq or base

    @staticmethod
    def _normalize_query(query: str) -> str:
        """Normalize legacy RAG prefixes such as "从文档中获取："."""
        return _strip_rag_routing_query(query)

    @staticmethod
    def _rewrite_query(query: str) -> str:
        """Normalize Chinese questions for better retrieval:
        - Remove filler particles (吗, 呢, 啊, 吧, 呀)
        - Normalize common patterns (怎么做→如何做, 有没有→是否有)
        - Strip excessive punctuation
        """
        import re

        q = (query or "").strip()
        if not q:
            return q

        # Remove trailing question/filler particles (strip ? first to catch 吗/呢 before ？)
        q = re.sub(r"[？?！!]+$", "", q)
        q = re.sub(r"[吗呢啊吧呀嘛哈哦喔]{1,2}$", "", q)
        q = re.sub(r"^(请问|我想问一下|我想知道|告诉我|请告诉我|帮我查一下|帮我查查|帮我看看)", "", q)

        # Normalize common patterns
        replacements = [
            ("怎么做", "如何操作"),
            ("怎么申请", "如何申请"),
            ("怎么办", "如何处理"),
            ("有没有", "是否有"),
            ("是不是", "是否是"),
            ("能不能", "是否可以"),
            ("会不会", "是否会"),
            ("行不行", "是否可行"),
            ("啥是", "什么是"),
            ("有啥", "有什么"),
            ("咋", "怎么"),
        ]
        for old, new in replacements:
            q = q.replace(old, new)

        # Collapse multiple spaces/punctuation
        q = re.sub(r"\s{2,}", " ", q)
        q = re.sub(r"[.。,，]{2,}", "。", q)

        return q.strip()

    @staticmethod
    def _expand_query_terms(query: str) -> list[str]:
        import re

        q = (query or "").strip().lower()
        if not q:
            return []

        terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", q)
        expanded: list[str] = []
        seen: set[str] = set()

        def add(term: str) -> None:
            term = term.strip().lower()
            if term and term not in seen:
                seen.add(term)
                expanded.append(term)

        for term in terms:
            add(term)

        synonym_map = {
            # 通用组织/实体
            "公司": ["企业", "单位", "组织", "机构"],
            "地址": ["地点", "所在地", "办公地址", "位置"],
            "电话": ["联系电话", "联系方式", "手机", "热线"],
            "邮箱": ["电子邮箱", "邮件", "mail", "email"],
            "联系人": ["对接人", "负责人", "联络人", "接口人"],
            "简介": ["概况", "介绍", "说明", "概述", "背景"],
            "信息": ["资料", "内容", "详情", "身份", "角色", "权限"],
            "联系方式": ["电话", "邮箱", "联系人", "通讯方式"],
            "公司信息": ["企业信息", "公司简介", "组织信息", "单位概况"],
            # 角色/权限
            "队长": [
                "负责人", "组长", "管理员", "leader", "captain",
                "录入大厅账号", "大厅账号", "有资质账号", "准入账号",
                "大厅操作员", "准入操作员", "资质账号"
            ],
            "管理员": ["admin", "administrator", "负责人", "主管", "组长"],
            "操作员": ["operator", "执行人", "工作人员", "经办人"],
            # 动作/流程
            "成为": ["申请", "加入", "晋升", "开通", "授权", "获得"],
            "申请": ["请求", "申领", "报名", "注册", "登记"],
            "操作": ["执行", "处理", "管理", "控制", "操纵"],
            "审核": ["审批", "复核", "审查", "核实", "核验"],
            "配置": ["设置", "设定", "参数", "选项", "属性"],
            # 身份/权限
            "身份": ["角色", "权限", "资格", "认证", "申请条件"],
            "权限": ["权利", "许可", "授权", "访问权限", "操作权限"],
            "资格": ["资质", "条件", "要求", "标准", "门槛"],
            "账号": ["账户", "用户", "id", "uid", "username"],
            # 任务/流程
            "任务": ["工作", "作业", "待办", "事项", "task"],
            "流程": ["步骤", "环节", "工序", "workflow", "pipeline"],
            "规则": ["规范", "制度", "条例", "规定", "章程"],
            "条件": ["要求", "标准", "门槛", "限制", "前置条件"],
            # 定义/说明类查询词
            "什么是": ["定义", "含义", "是指", "意思是", "说明", "介绍", "啥是", "什么叫"],
            "定义": ["是什么", "含义", "解释", "说明", "概念", "界定"],
            "如何": ["怎么", "怎样", "方法", "步骤", "流程"],
            "原因": ["为什么", "为何", "起因", "理由", "缘故"],
            "区别": ["差异", "不同", "对比", "比较", "分别"],
        }
        for term in terms:
            for key, values in synonym_map.items():
                if key in term:
                    for value in values:
                        add(value)
        return expanded

    def __init__(self) -> None:
        super().__init__("rag")

    def _build_llmwiki_evidence(
        self,
        query: str,
        search_query: str,
        llmwiki_chunks: list[Any],
        citations: list[dict[str, Any]],
        existing_ids: set[str],
    ) -> list[dict[str, Any]]:
        llmwiki_entries: list[dict[str, Any]] = []
        for idx, c in enumerate(llmwiki_chunks, start=1):
            meta = c.metadata if isinstance(c.metadata, dict) else {}
            title = str(meta.get("title") or "Document")
            question = str(meta.get("question") or "文档摘要").strip()
            answer = "".join(ch for ch in (c.content or "") if ch.isprintable() or ch in "\n\t").strip()[:500]
            score = float(getattr(c, "score", 0.0) or 0.0)
            entry_id = str(meta.get("chunk_id") or f"{meta.get('document_id')}::wiki::{question[:60]}")
            if entry_id in existing_ids:
                continue
            existing_ids.add(entry_id)
            llmwiki_entries.append(
                {
                    "source_type": "llmwiki",
                    "id": entry_id,
                    "title": title,
                    "question": question,
                    "text": answer,
                    "answer": answer,
                    "score": score,
                    "document_id": meta.get("document_id"),
                    "chunk_id": meta.get("chunk_id"),
                    "keywords": meta.get("keywords", []),
                    "matched_query": search_query,
                    "query": query,
                    "evidence_tier": "factual" if score >= 0.45 else "supporting",
                }
            )
            citations.append(
                {
                    "id": len(citations) + 1,
                    "title": f"{title} · {question}",
                    "url": "",
                    "snippet": answer[:120],
                    "document_id": meta.get("document_id"),
                    "chunk_id": meta.get("chunk_id"),
                    "source_type": "llmwiki",
                }
            )
        return llmwiki_entries

    @staticmethod
    def _is_definition_query(query: str) -> bool:
        """判断是否为定义类查询（如"什么是X？"、"X的定义"）"""
        q = (query or "").lower()
        return any(k in q for k in [
            "什么是", "定义", "含义", "是指", "什么意思",
            "啥是", "什么叫", "指什么", "解释一下"
        ])

    @staticmethod
    def _classify_query_type(query: str) -> dict[str, Any]:
        """Classify query into type + hints for retrieval strategy tuning.

        Returns dict with:
          - query_type: one of definition | fact | procedure | comparison | memory | general
          - hints: list of strategy hints for downstream use
        """
        q = (query or "").lower()

        definition_kw = ["什么是", "定义", "含义", "是指", "什么意思", "啥是", "什么叫", "指什么", "解释一下", "概念"]
        fact_kw = ["是谁", "多少", "什么时候", "在哪里", "哪个", "有没有", "是否", "联系方式", "地址", "电话", "邮箱"]
        procedure_kw = ["怎么做", "如何", "步骤", "流程", "怎样", "方法", "怎么申请", "如何成为", "怎么操作"]
        comparison_kw = ["区别", "对比", "不同", "一样吗", "哪个更好", "比较", "vs"]
        memory_kw = ["偏好", "之前", "上次", "历史", "我记得", "我的设置", "我设置", "记忆"]

        scores = {
            "definition": sum(1 for k in definition_kw if k in q),
            "fact": sum(1 for k in fact_kw if k in q),
            "procedure": sum(1 for k in procedure_kw if k in q),
            "comparison": sum(1 for k in comparison_kw if k in q),
            "memory": sum(1 for k in memory_kw if k in q),
        }
        best_type = max(scores, key=lambda k: scores[k])
        best_score = scores[best_type]

        if best_score == 0:
            query_type = "general"
        else:
            query_type = best_type

        hints: list[str] = []
        if query_type == "definition":
            hints = ["prefer_llmwiki", "lower_threshold"]
        elif query_type == "fact":
            hints = ["prefer_documents", "higher_precision"]
        elif query_type == "procedure":
            hints = ["prefer_chunks_with_steps", "lexical_heavy"]
        elif query_type == "comparison":
            hints = ["need_multi_source", "wider_retrieval"]
        elif query_type == "memory":
            hints = ["prefer_memory", "documents_secondary"]

        return {"query_type": query_type, "hints": hints}

    def _build_vector_evidence(
        self,
        query: str,
        query_terms: list[str],
        search_query: str,
        doc_chunks: list[Any],
        min_score: float,
        citations: list[dict[str, Any]],
        seen_chunks: set[str],
    ) -> list[dict[str, Any]]:
        vector_chunks: list[dict[str, Any]] = []
        for idx, c in enumerate(doc_chunks, start=1):
            meta = c.metadata if isinstance(c.metadata, dict) else {}
            title = str(meta.get("title") or meta.get("document_title") or "Document")
            txt = "".join(ch for ch in (c.content or "") if ch.isprintable() or ch in "\n\t").strip()[:500]
            score = float(getattr(c, "score", 0.0) or 0.0)
            chunk_id = f"{meta.get('document_id')}::{meta.get('chunk_index')}::{txt[:80]}"
            if chunk_id in seen_chunks:
                continue

            title_l = title.lower()
            query_l = query.lower()
            title_bonus = 0.0
            if title_l and query_l and (query_l in title_l or title_l in query_l):
                title_bonus += 0.22
            if query_terms and any(term in title_l for term in query_terms):
                title_bonus += 0.12
            if query_terms and any(term in txt.lower() for term in query_terms[:6]):
                title_bonus += 0.08
            score = min(0.99, score + title_bonus)
            if score < min_score:
                continue

            seen_chunks.add(chunk_id)
            evidence_tier = "factual" if score >= 0.50 else "supporting"
            vector_chunks.append(
                {
                    "source_type": "document",
                    "id": f"doc_{idx}",
                    "title": title,
                    "text": txt,
                    "score": score,
                    "chunk_index": meta.get("chunk_index"),
                    "document_id": meta.get("document_id"),
                    "matched_query": search_query,
                    "evidence_tier": evidence_tier,
                }
            )
            citations.append(
                {
                    "id": len(citations) + 1,
                    "title": title,
                    "url": "",
                    "snippet": txt[:120],
                    "chunk_index": meta.get("chunk_index"),
                    "document_id": meta.get("document_id"),
                    "source_type": "document",
                }
            )
        return vector_chunks

    async def _rerank_evidence(
        self,
        query: str,
        evidence: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Re-rank evidence using neural reranker (qwen3-vl-rerank via DashScope).

        Only applies when settings.rag_rerank_enabled is True and candidates exceed 1.
        Falls back gracefully to original scoring on any error.
        """
        if not evidence or len(evidence) <= 1:
            return evidence
        if not settings.rag_rerank_enabled:
            return evidence

        try:
            reranker = get_reranker()
            texts = [str(e.get("text") or e.get("answer") or "")[:800] for e in evidence]
            if not any(t.strip() for t in texts):
                return evidence

            ranked = await reranker.rerank(query, texts, top_k=min(top_k * 3, len(texts)))
            if not ranked:
                return evidence

            rerank_score_map: dict[str, float] = {}
            for rr in ranked:
                normalized_score = max(0.0, min(1.0, rr.score))
                rerank_score_map[rr.text] = normalized_score

            for e in evidence:
                txt = str(e.get("text") or e.get("answer") or "")[:800]
                if txt in rerank_score_map:
                    original_score = float(e.get("score", 0.0) or 0.0)
                    rerank_score = rerank_score_map[txt]
                    # Blend: 60% reranker, 40% original retrieval score
                    e["score"] = round(original_score * 0.40 + rerank_score * 0.60, 4)
                    e["_rerank_score"] = round(rerank_score, 4)

            return evidence
        except Exception:
            return evidence

    async def execute(self, task: TaskMessage) -> AgentResult:
        try:
            raw_query = self._retrieval_query_from_task(task)
            query = self._normalize_query(raw_query)
            if not query:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error="query is required",
                    evidence_objects=[
                        self._make_evidence_object(
                            content="query is required",
                            source_type="validation",
                            credibility=0.0,
                            relevance=0.0,
                            turn_outcome="error",
                        )
                    ],
                )

            # Rewrite query for better retrieval (remove fillers, normalize patterns)
            rewritten_query = self._rewrite_query(query)

            user_id = (task.user_id or str(task.params.get("user_id", ""))).strip() or "shared"
            tenant_id = str(task.params.get("tenant_id", "") or "").strip() or None
            workspace_id = str(task.params.get("workspace_id", "") or "").strip() or None
            project_id = str(task.params.get("project_id", "") or "").strip() or None
            retrieval_scope: dict[str, Any] = {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
            }
            if project_id:
                retrieval_scope["project_id"] = project_id

            top_k = int(task.params.get("top_k", 5))
            top_k = max(1, min(top_k, 20))
            llmwiki_top_k = int(task.params.get("llmwiki_top_k", settings.llmwiki_top_k or 3))
            llmwiki_top_k = max(1, min(llmwiki_top_k, 10))
            sources = task.params.get("sources", ["knowledge", "documents", "semantic_memory"])
            if not isinstance(sources, list):
                sources = ["knowledge", "documents", "semantic_memory"]
            if not (
                getattr(settings, "knowledge_orchestration_enabled", True)
                and getattr(settings, "knowledge_query_enabled", True)
            ):
                sources = [source for source in sources if source != "knowledge"]

            # Query type classification for strategy tuning (use rewritten for better matching)
            qtype_info = self._classify_query_type(rewritten_query)
            query_type = qtype_info["query_type"]
            hints = qtype_info["hints"]

            # Base retrieval threshold — adjusted by query type
            configured_min_score = task.params.get("min_score")
            if configured_min_score is None:
                configured_min_score = task.params.get(
                    "min_evidence_score",
                    getattr(settings, "rag_min_evidence_score", os.getenv("RAG_MIN_SCORE", "0.35")),
                )
            min_score = float(configured_min_score)
            if "lower_threshold" in hints:
                min_score = max(0.20, min_score - 0.08)
            elif "higher_precision" in hints:
                min_score = min(0.55, min_score + 0.05)

            # LLMWiki top_k adjustment for definition queries
            effective_llmwiki_top_k = llmwiki_top_k
            if "prefer_llmwiki" in hints:
                effective_llmwiki_top_k = min(10, llmwiki_top_k + 2)

            # Evidence quality gate
            evidence_gate = DocumentEvidenceGate(min_score=min_score, min_gap=0.05)

            evidence: list[dict[str, Any]] = []
            citations: list[dict[str, Any]] = []
            query_terms = self._expand_query_terms(rewritten_query)
            rag_plan = build_rag_query_plan(
                raw_query=raw_query,
                normalized_query=query,
                rewritten_query=rewritten_query,
                query_type=query_type,
                hints=hints,
                query_terms=query_terms,
                sources=sources,
                top_k=top_k,
                llmwiki_top_k=effective_llmwiki_top_k,
                min_score=min_score,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                params=task.params,
            )
            doc_evidence_count = 0
            llmwiki_entries: list[dict[str, Any]] = []
            vector_chunks: list[dict[str, Any]] = []

            if "knowledge" in sources:
                knowledge_results = await asyncio.gather(
                    *[
                        search_knowledge(
                            query=search_query,
                            user_id=user_id,
                            **retrieval_scope,
                            top_k=max(top_k, 6),
                            query_type=query_type,
                            session_id=task.session_id or task.params.get("session_id"),
                        )
                        for search_query in (rag_plan.query_variants or [rewritten_query])
                    ],
                    return_exceptions=True,
                )
                seen_knowledge: set[str] = set()
                for result in knowledge_results:
                    if isinstance(result, Exception):
                        continue
                    for item in result:
                        key = f"{item.get('source_type')}:{item.get('id')}"
                        if key in seen_knowledge:
                            continue
                        seen_knowledge.add(key)
                        item["matched_query"] = rewritten_query
                        evidence.append(item)
                        citations.append(
                            {
                                "id": len(citations) + 1,
                                "title": item.get("title") or "Knowledge",
                                "url": "",
                                "snippet": str(item.get("text") or "")[:160],
                                "source_type": item.get("source_type", "knowledge"),
                                "knowledge_page_id": item.get("knowledge_page_id"),
                                "claim_id": item.get("claim_id"),
                                "relation_id": item.get("relation_id"),
                                "source_id": item.get("source_id"),
                                "source_version_id": item.get("source_version_id"),
                                "provenance": dict(item.get("provenance") or {}),
                            }
                        )

            if "documents" in sources:
                search_queries = list(rag_plan.query_variants or [rewritten_query])

                seen_chunks: set[str] = set()
                seen_llmwiki_ids: set[str] = set()

                # Run all search queries in parallel (was serial — major latency fix)
                async def _search_one(sq: str):
                    doc_chunks, wiki_chunks = await asyncio.gather(
                        DocumentPlugin().search_chunks(
                            query=sq,
                            user_id=user_id,
                            top_k=max(top_k, 8),
                            **retrieval_scope,
                        ),
                        DocumentPlugin().search_llmwiki(
                            query=sq,
                            user_id=user_id,
                            top_k=effective_llmwiki_top_k,
                            **retrieval_scope,
                        ),
                    )
                    return sq, doc_chunks, wiki_chunks

                parallel_results = await asyncio.gather(
                    *[_search_one(sq) for sq in search_queries],
                    return_exceptions=True,
                )

                for result in parallel_results:
                    if isinstance(result, Exception):
                        continue
                    sq, doc_chunks, wiki_chunks = result
                    llmwiki_entries.extend(
                        self._build_llmwiki_evidence(
                            query=query, search_query=sq,
                            llmwiki_chunks=wiki_chunks, citations=citations,
                            existing_ids=seen_llmwiki_ids,
                        )
                    )
                    new_vector_chunks = self._build_vector_evidence(
                        query=query, query_terms=query_terms, search_query=sq,
                        doc_chunks=doc_chunks, min_score=min_score,
                        citations=citations, seen_chunks=seen_chunks,
                    )
                    vector_chunks.extend(new_vector_chunks)
                    doc_evidence_count += len(new_vector_chunks)

                evidence.extend(llmwiki_entries)
                evidence.extend(vector_chunks)

            is_memory_intent = query_type == "memory" or any(
                k in rewritten_query.lower() for k in ["记忆", "偏好", "之前", "上次", "历史", "用户设置", "profile", "preference"]
            )
            if (doc_evidence_count == 0 and not llmwiki_entries or is_memory_intent) and ("semantic_memory" in sources or "episodic_memory" in sources):
                async with AsyncSessionLocal() as db:
                    q = (
                        select(UserMemory)
                        .where(UserMemory.enabled == True)  # noqa: E712
                        .where(UserMemory.user_id == user_id)
                        .order_by(UserMemory.updated_at.desc())
                        .limit(300)
                    )
                    r = await db.execute(q)
                    rows = r.scalars().all()

                import re
                q_tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{1,}", rewritten_query.lower())
                for m in rows:
                    mt = str(m.memory_type or "")
                    if mt == "semantic" and "semantic_memory" not in sources:
                        continue
                    if mt == "episodic" and "episodic_memory" not in sources:
                        continue

                    hay = f"{m.title or ''} {m.content or ''}".lower()
                    hit = any(tok in hay for tok in q_tokens) if q_tokens else False
                    if not hit:
                        if not (mt == "semantic" and getattr(m, "pinned", False) and is_memory_intent):
                            continue

                    txt = (m.content or "")[:500]
                    memory_tier = "supporting" if is_memory_intent else "contextual"
                    memory_score = 0.72 if hit else 0.55
                    if not is_memory_intent:
                        memory_score = max(0.35, memory_score - 0.15)
                    evidence.append(
                        {
                            "source_type": "memory" if mt == "semantic" else "episodic",
                            "id": m.id,
                            "title": m.title or "Memory",
                            "text": txt,
                            "score": memory_score,
                            "memory_type": mt,
                            "evidence_tier": memory_tier,
                        }
                    )
                    if len(evidence) >= max(top_k * 3, 10):
                        break

            seen = set()
            deduped: list[dict[str, Any]] = []
            for e in evidence:
                source_type_for_weight = str(e.get("source_type") or "document")
                original_score = float(e.get("score", 0.0) or 0.0)
                e.setdefault("raw_score", round(original_score, 4))
                e["lane_weight"] = round(lane_weight(rag_plan, source_type_for_weight), 4)
                e["score"] = round(min(0.999, original_score * float(e["lane_weight"])), 4)
                key = f"{e.get('source_type')}::{e.get('id')}::{(e.get('text') or '')[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(e)

            rrf_enabled = bool(getattr(settings, "rag_rrf_fusion_enabled", True))
            if rrf_enabled and deduped:
                from services.rag_retrieval_fusion import reciprocal_rank_fusion

                deduped = reciprocal_rank_fusion(
                    deduped,
                    k=int(getattr(settings, "rag_rrf_k", 60) or 60),
                    top_n=max(top_k * 3, 20),
                    lane_weights={lane.name: lane.weight for lane in rag_plan.lanes},
                )

            sorted_chunks = sorted(deduped, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)[:top_k]
            sorted_knowledge_chunks = sorted(
                [e for e in deduped if str(e.get("source_type", "")).startswith("knowledge")],
                key=lambda x: float(x.get("score", 0.0) or 0.0),
                reverse=True,
            )[:top_k]
            sorted_llmwiki_entries = sorted(llmwiki_entries, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)[:llmwiki_top_k]
            sorted_vector_chunks = sorted(vector_chunks, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)[:top_k]

            # Neural rerank via qwen3-vl-rerank (when enabled) — rerank deduped evidence
            if settings.rag_rerank_enabled and deduped:
                deduped = await self._rerank_evidence(rewritten_query, deduped, top_k)
                sorted_chunks = sorted(deduped, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)[:top_k]
                sorted_knowledge_chunks = sorted(
                    [e for e in deduped if str(e.get("source_type", "")).startswith("knowledge")],
                    key=lambda x: float(x.get("score", 0.0) or 0.0),
                    reverse=True,
                )[:top_k]
                sorted_llmwiki_entries = sorted(
                    [e for e in deduped if e.get("source_type") == "llmwiki"],
                    key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True,
                )[:llmwiki_top_k]
                sorted_vector_chunks = sorted(
                    [e for e in deduped if e.get("source_type") == "document"],
                    key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True,
                )[:top_k]

            content_parts = []
            for i, chunk in enumerate(sorted_knowledge_chunks, start=1):
                title_ctx = chunk.get("title", "")
                prefix = f"[{title_ctx}] " if title_ctx else ""
                content_parts.append(
                    f"[Knowledge {i}] stage={chunk.get('disclosure_stage', '-')} "
                    f"tier={chunk.get('evidence_tier', '-')} score={float(chunk.get('score', 0.0)):.3f}\n"
                    f"{prefix}{chunk.get('text', '')[:300]}"
                )
            for i, chunk in enumerate(sorted_llmwiki_entries, start=1):
                title_ctx = chunk.get('title', '')
                prefix = f"[{title_ctx}] " if title_ctx else ""
                content_parts.append(
                    f"[LLMWiki {i}] {chunk.get('question', '摘要')} tier={chunk.get('evidence_tier', '-')} score={float(chunk.get('score', 0.0)):.3f}\n"
                    f"{prefix}{chunk.get('answer', '')[:220]}"
                )
            for i, chunk in enumerate(sorted_vector_chunks[: max(1, top_k - len(sorted_llmwiki_entries))], start=1):
                title_ctx = chunk.get('title', '')
                prefix = f"[{title_ctx}] " if title_ctx else ""
                content_parts.append(
                    f"[Doc {i}] tier={chunk.get('evidence_tier', '-')} score={float(chunk.get('score', 0.0)):.3f}\n"
                    f"{prefix}{chunk.get('text', '')[:240]}"
                )
            if not content_parts:
                for i, chunk in enumerate(sorted_chunks, start=1):
                    title_ctx = chunk.get('title', '')
                    prefix = f"[{title_ctx}] " if title_ctx else ""
                    content_parts.append(
                        f"[{i}] source={chunk.get('source_type')} tier={chunk.get('evidence_tier', '-')} score={float(chunk.get('score', 0.0)):.3f}\n"
                        f"{prefix}{chunk.get('text', '')[:240]}"
                    )
            content = "\n\n".join(content_parts) if content_parts else (
                "当前账户下暂未上传任何文档。请先在「文档」页面上传知识库文档（PDF/DOCX/TXT/MD 等格式），"
                "上传后即可使用 /rag 模式进行文档检索与问答。\n\n"
                "如果不需要检索文档，可以使用 /web 联网搜索，或直接输入问题进行通用问答。"
            )

            if not sorted_chunks and query_terms and "documents" in sources:
                seen_chunks = {
                    f"{item.get('document_id')}::{item.get('chunk_index')}::{str(item.get('text') or '')[:80]}"
                    for item in vector_chunks
                }
                fallback_queries = [rewritten_query, " ".join(query_terms[:6])]
                # Run fallback searches in parallel
                parallel_fallback = await asyncio.gather(
                    *[
                        DocumentPlugin().search_chunks(
                            query=sq,
                            user_id=user_id,
                            top_k=max(top_k, 8),
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            project_id=project_id,
                        )
                        for sq in fallback_queries
                    ],
                    return_exceptions=True,
                )
                for result in parallel_fallback:
                    if isinstance(result, Exception):
                        continue
                    doc_chunks = result
                    for idx, c in enumerate(doc_chunks, start=1):
                        meta = c.metadata if isinstance(c.metadata, dict) else {}
                        title = str(meta.get("title") or meta.get("document_title") or "Document")
                        txt = "".join(ch for ch in (c.content or "") if ch.isprintable() or ch in "\n\t").strip()[:500]
                        chunk_id = f"{meta.get('document_id')}::{meta.get('chunk_index')}::{txt[:80]}"
                        if chunk_id in seen_chunks:
                            continue
                        seen_chunks.add(chunk_id)
                        fallback_chunk = {
                            "source_type": "document",
                            "id": f"doc_fallback_{idx}",
                            "title": title,
                            "text": txt,
                            "score": max(float(getattr(c, "score", 0.0) or 0.0), 0.25),
                            "chunk_index": meta.get("chunk_index"),
                            "document_id": meta.get("document_id"),
                            "matched_query": rewritten_query,
                            "evidence_tier": "supporting",
                        }
                        evidence.append(fallback_chunk)
                        vector_chunks.append(fallback_chunk)
                        citations.append(
                            {
                                "id": len(citations) + 1,
                                "title": title,
                                "url": "",
                                "snippet": txt[:120],
                                "chunk_index": meta.get("chunk_index"),
                                "document_id": meta.get("document_id"),
                                "source_type": "document",
                            }
                        )

                sorted_chunks = sorted(evidence, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)[:top_k]
                sorted_knowledge_chunks = sorted(
                    [e for e in sorted_chunks if str(e.get("source_type", "")).startswith("knowledge")],
                    key=lambda x: float(x.get("score", 0.0) or 0.0),
                    reverse=True,
                )[:top_k]
                sorted_vector_chunks = sorted(vector_chunks, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)[:top_k]
                if not content_parts and sorted_vector_chunks:
                    content_parts = [
                        (
                            f"[Doc {i}] tier={chunk.get('evidence_tier', '-')} "
                            f"score={float(chunk.get('score', 0.0)):.3f}\n"
                            f"[{chunk.get('title', '')}] {chunk.get('text', '')[:240]}"
                        )
                        for i, chunk in enumerate(sorted_vector_chunks[:top_k], start=1)
                    ]
                    content = "\n\n".join(content_parts)

            # Improved confidence: weighted by max_score, avg_score, score spread, source diversity
            if sorted_chunks:
                scores = [float(chunk.get("score", 0.0) or 0.0) for chunk in sorted_chunks]
                avg_score = sum(scores) / len(scores)
                max_score = max(scores)
                score_spread = (scores[0] - scores[-1]) / max(0.01, scores[0]) if len(scores) >= 2 else 0.0
                source_types = {chunk.get("source_type") for chunk in sorted_chunks}
                source_diversity = min(1.0, len(source_types) / 3.0)

                top1_top3_gap = 0.0
                if len(scores) >= 3:
                    top1_top3_gap = scores[0] - scores[2]
                elif len(scores) >= 2:
                    top1_top3_gap = scores[0] - scores[-1]

                confidence = (
                    0.30
                    + 0.25 * max_score
                    + 0.15 * avg_score
                    + 0.12 * source_diversity
                    + 0.10 * min(1.0, score_spread * 2)
                )
                confidence = min(0.95, max(0.25, confidence))

                # Evidence quality gate check
                gate_input = [
                    ScoredDocumentChunk(
                        chunk=None,  # type: ignore[arg-type]
                        title=chunk.get("title", ""),
                        score=chunk.get("score", 0.0),
                    )
                    for chunk in sorted_chunks
                    if chunk.get("source_type") == "document"
                ]
                gated = evidence_gate.passes(gate_input) if gate_input else bool(sorted_chunks)
                top_text = "\n".join(
                    str(chunk.get("text") or chunk.get("answer") or "")[:300]
                    for chunk in sorted_chunks[:3]
                )
                user_anchor = _strip_rag_routing_query(query) or rewritten_query or query
                anchor_terms = query_terms or _substantive_query_terms(user_anchor)
                anchor_query = " ".join(anchor_terms[:8]) if anchor_terms else user_anchor
                anchor_score = max(
                    relevance_score(user_anchor, top_text),
                    relevance_score(rewritten_query, top_text),
                    relevance_score(anchor_query, top_text),
                )
                retrieval_strong = max_score >= min_score and bool(sorted_chunks)
                answerability_decision = assess_answerability(
                    has_evidence=bool(sorted_chunks),
                    retrieval_strong=retrieval_strong,
                    gated=gated,
                    confidence=confidence,
                    anchor_score=anchor_score,
                    max_score=max_score,
                    min_score=min_score,
                )
                answerable = bool(answerability_decision["answerable"])
            else:
                avg_score = 0.0
                max_score = 0.0
                confidence = 0.25
                top1_top3_gap = 0.0
                anchor_score = 0.0
                answerable = False
                gated = False
                retrieval_strong = False
                answerability_decision = assess_answerability(
                    has_evidence=False,
                    retrieval_strong=False,
                    gated=False,
                    confidence=confidence,
                    anchor_score=anchor_score,
                    max_score=max_score,
                    min_score=min_score,
                )

            if not answerable:
                display_query = _strip_rag_routing_query(query) or query
                if retrieval_strong and sorted_chunks:
                    content = (
                        f"检索到与「{display_query}」相关的片段，但相关性锚定偏弱"
                        f"（anchor={anchor_score:.2f}），将交由融合层审慎作答。"
                    )
                    confidence = min(confidence, 0.42)
                else:
                    sorted_chunks = []
                    sorted_knowledge_chunks = []
                    sorted_vector_chunks = []
                    sorted_llmwiki_entries = []
                    content = (
                        f"未在知识库中找到与「{display_query}」直接相关的内容。"
                        "请补充更具体的问题，或上传相关文档后再试。"
                    )
                    confidence = min(confidence, 0.2)
                try:
                    from kernel.agent_runtime.learning_hook import record_agent_learning_signal

                    await record_agent_learning_signal(
                        agent_type=self.agent_type,
                        task_id=task.task_id,
                        session_id=str(task.session_id or ""),
                        passed=False,
                        confidence=confidence,
                        evidence_quality=float(max_score),
                        metadata={"query_type": query_type, "query_preview": query[:120]},
                    )
                except Exception:
                    pass

            def _citation_for_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
                for citation in citations:
                    if not isinstance(citation, dict):
                        continue
                    same_doc = citation.get("document_id") and citation.get("document_id") == chunk.get("document_id")
                    same_chunk = (
                        citation.get("chunk_index") is not None
                        and citation.get("chunk_index") == chunk.get("chunk_index")
                    )
                    same_type = citation.get("source_type") == chunk.get("source_type")
                    same_knowledge = (
                        citation.get("claim_id")
                        and citation.get("claim_id") == chunk.get("claim_id")
                    ) or (
                        citation.get("knowledge_page_id")
                        and citation.get("knowledge_page_id") == chunk.get("knowledge_page_id")
                    ) or (
                        citation.get("relation_id")
                        and citation.get("relation_id") == chunk.get("relation_id")
                    )
                    if same_type and (same_doc or same_chunk or same_knowledge):
                        return citation
                return {}

            normalized_rag_evidence = [
                normalize_rag_evidence(
                    ch,
                    plan=rag_plan,
                    rank=i,
                    citation=_citation_for_chunk(ch),
                )
                for i, ch in enumerate(sorted_chunks, start=1)
                if isinstance(ch, dict)
            ]
            protocol_by_id = {
                str(item.get("id")): item
                for item in normalized_rag_evidence
                if isinstance(item, dict)
            }

            evidence_items = []
            evidence_objects = []
            for ch in sorted_chunks:
                matching_citations = [
                    citation for citation in citations
                    if (
                        citation.get("document_id") == ch.get("document_id")
                        or citation.get("chunk_id") == ch.get("chunk_id")
                        or citation.get("knowledge_page_id") == ch.get("knowledge_page_id")
                        or citation.get("claim_id") == ch.get("claim_id")
                        or citation.get("relation_id") == ch.get("relation_id")
                    )
                ]
                protocol = protocol_by_id.get(str(ch.get("id"))) or normalize_rag_evidence(
                    ch,
                    plan=rag_plan,
                    citation=_citation_for_chunk(ch),
                )
                evidence_items.append(
                    self._make_evidence(
                        source=ch.get("title", ""),
                        source_type=ch.get("source_type", "document"),
                        payload={"text": ch.get("text", ""), "title": ch.get("title", ""), "id": ch.get("id", "")},
                        credibility=ch.get("score", 0.5),
                        relevance=ch.get("score", 0.5),
                        provenance=ch.get("id", ""),
                        evidence_tier=ch.get("evidence_tier", "contextual"),
                    )
                )
                text = str(ch.get("text") or ch.get("answer") or "")[:4000]
                if text:
                    evidence_objects.append(
                        self._make_evidence_object(
                            content=text,
                            source_type=str(ch.get("source_type", "document")),
                            credibility=float(ch.get("score", 0.5)),
                            relevance=float(ch.get("score", 0.5)),
                            chunk_id=ch.get("id", ""),
                            evidence_tier=ch.get("evidence_tier", "contextual"),
                            rag_evidence=protocol,
                            access_scope=rag_plan.filters,
                            citations=matching_citations[:3],
                            provenance=ch.get("provenance") or {},
                            knowledge_page_id=ch.get("knowledge_page_id"),
                            claim_id=ch.get("claim_id"),
                            relation_id=ch.get("relation_id"),
                            source_version_id=ch.get("source_version_id"),
                            evidence_chunk_id=ch.get("chunk_id"),
                            evidence_start=ch.get("evidence_start"),
                            evidence_end=ch.get("evidence_end"),
                        )
                    )
            from kernel.result_reference import ResultRef, serialize_refs

            result_refs: list[ResultRef] = []
            for i, ch in enumerate((sorted_vector_chunks or [])[:5]):
                result_refs.append(ResultRef(
                    ref_id=f"doc_chunk:{ch.get('id', task.task_id)}",
                    type="doc_chunk",
                    title=f"Chunk: {ch.get('title', 'Untitled')}",
                    summary=(str(ch.get('text', '')) or '')[:120],
                    payload={"chunk": ch, "score": ch.get("score", 0)},
                    source_agent="rag",
                    message_id=task.task_id,
                ))
            for c in (citations or [])[:5]:
                result_refs.append(ResultRef(
                    ref_id=f"citation:{c.get('source_name', task.task_id)}" if isinstance(c, dict) else f"citation:{task.task_id}",
                    type="citation",
                    title=f"Citation: {c.get('source_name', 'Unknown')}",
                    summary=c.get('content_snippet', '')[:120] if isinstance(c, dict) else str(c)[:120],
                    payload={"citation": c} if isinstance(c, dict) else {},
                    source_agent="rag",
                    message_id=task.task_id,
                ))
            rag_intel: dict[str, Any] = {}
            try:
                from services.rag_evidence_intelligence import enrich_evidence_intelligence

                chunk_dicts = []
                for ch in sorted_chunks or []:
                    if isinstance(ch, dict):
                        chunk_dicts.append(
                            {
                                "id": ch.get("id", ""),
                                "content": ch.get("text", ""),
                                "source": ch.get("title", ""),
                                "credibility_score": ch.get("score", 0.5),
                                "relevance_score": ch.get("score", 0.5),
                            }
                        )
                if chunk_dicts:
                    rag_intel = enrich_evidence_intelligence(
                        chunk_dicts, query=query, source_kind="document"
                    )
                    contradictions = rag_intel.get("contradictions") or []
                    claim = (rag_intel.get("claim_verification") or {})
                    contradiction_count = len(contradictions) if isinstance(contradictions, list) else 0
                    claim_needs_review = bool(isinstance(claim, dict) and claim.get("needs_review"))
                    answerability_decision = assess_answerability(
                        has_evidence=bool(sorted_chunks),
                        retrieval_strong=retrieval_strong,
                        gated=gated,
                        confidence=confidence,
                        anchor_score=anchor_score,
                        max_score=max_score,
                        min_score=min_score,
                        contradiction_count=contradiction_count,
                        claim_needs_review=claim_needs_review,
                    )
                    if isinstance(claim, dict) and claim.get("needs_review") and answerable:
                        confidence = min(confidence, 0.45)
                        for ch in sorted_chunks:
                            if isinstance(ch, dict):
                                ch["needs_review"] = True
                        if int(claim.get("unanchored_count") or 0) >= 2:
                            answerable = False
                            content = (
                                f"检索片段与「{query}」锚定不足，已抑制自动作答。"
                                "请补充更具体的问题或上传相关文档。"
                            )
                            confidence = min(confidence, 0.3)
                            answerability_decision["answerable"] = False
                            answerability_decision["state"] = "unanswerable"
                            answerability_decision.setdefault("reasons", []).append("claim_anchor_suppressed")
                    if contradictions and answerable:
                        confidence = min(confidence, 0.55)
                        for ch in sorted_chunks:
                            if isinstance(ch, dict):
                                ch["needs_review"] = True
                        if len(contradictions) >= 2:
                            answerable = False
                            content = (
                                f"知识库中关于「{query}」存在不一致表述，已抑制自动作答。"
                                "请查看引用片段或补充更具体的问题。"
                            )
                            confidence = min(confidence, 0.35)
                            answerability_decision["answerable"] = False
                            answerability_decision["state"] = "conflict"
                            answerability_decision.setdefault("reasons", []).append("contradiction_suppressed")
            except Exception:
                pass

            try:
                from kernel.agent_runtime.learning_hook import record_agent_learning_signal

                await record_agent_learning_signal(
                    agent_type=self.agent_type,
                    task_id=task.task_id,
                    session_id=str(task.session_id or ""),
                    passed=bool(answerable),
                    confidence=float(confidence),
                    evidence_quality=float(max_score),
                    metadata={
                        "query_type": query_type,
                        "query_preview": query[:120],
                        "rewritten_query": rewritten_query[:120],
                    },
                )
            except Exception:
                pass

            quality_metadata = {
                "avg_score": avg_score,
                "max_score": max_score,
                "top1_top3_gap": top1_top3_gap,
                "relevance_anchor": anchor_score,
                "sufficient": avg_score >= float(task.params.get("min_evidence_score", os.getenv("RAG_MIN_SCORE", "0.35"))),
                "answerable": answerable,
                "answerability": answerability_decision,
                "answerability_state": answerability_decision.get("state"),
                "gated": gated,
            }
            rag_trace = build_rag_trace(
                plan=rag_plan,
                total_retrieved=len(evidence),
                deduped_count=len(deduped),
                final_count=len(sorted_chunks),
                quality=quality_metadata,
            )

            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=content,
                confidence=confidence,
                metadata={
                    "chunks": sorted_chunks,
                    "vector_chunks": sorted_vector_chunks,
                    "llmwiki_entries": sorted_llmwiki_entries,
                    "total_retrieved": len(evidence),
                    "top_k": top_k,
                    "sources": sources,
                    "citations": citations,
                    "query_type": query_type,
                    "rag_query_plan": rag_plan.to_dict(),
                    "rag_trace": rag_trace,
                    "rag_evidence_objects": normalized_rag_evidence,
                    "result_refs": serialize_refs(result_refs),
                    "quality": quality_metadata,
                    "rag_evidence_intelligence": rag_intel,
                },
                evidence=evidence_items,
                evidence_objects=evidence_objects,
            )
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error=err,
                evidence_objects=[
                    self._make_evidence_object(
                        content=err[:2000],
                        source_type="rag_execution",
                        credibility=0.0,
                        relevance=0.0,
                        turn_outcome="error",
                    )
                ],
            )
