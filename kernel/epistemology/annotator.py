"""自动标注器：按 agent 来源附加证据层级。"""

from __future__ import annotations

from typing import Any

from kernel.epistemology.evidence import (
    AnnotatedContent,
    AnnotatedResponse,
    Citation,
    EvidenceAnnotation,
    EvidenceLevel,
    SourceType,
)


class ContentAnnotator:
    def annotate_model_response(self, content: str, context_sources: list[dict[str, Any]] | None = None) -> AnnotatedResponse:
        annotation = EvidenceAnnotation(
            level=EvidenceLevel.INFERENCE,
            source_type=SourceType.MODEL_INFERENCE,
            citations=[],
            confidence=0.7,
        )
        return AnnotatedResponse(fragments=[AnnotatedContent(text=content, annotation=annotation)], metadata={"agent_type": "model"})

    def annotate_agent_result(
        self,
        content: str,
        agent_type: str,
        metadata: dict[str, Any],
        citations: list[dict[str, Any]] | None = None,
    ) -> AnnotatedResponse:
        level_map = {
            "data": EvidenceLevel.FACT,
            "rag": EvidenceLevel.DOCUMENT,
            "web": EvidenceLevel.SEARCH,
            "memory": EvidenceLevel.MEMORY,
            "tool": EvidenceLevel.INFERENCE,
        }
        source_map = {
            "data": SourceType.DATABASE,
            "rag": SourceType.DOCUMENT,
            "web": SourceType.WEB_SEARCH,
            "memory": SourceType.USER_MEMORY,
            "tool": SourceType.TOOL_OUTPUT,
        }
        level = level_map.get(agent_type, EvidenceLevel.INFERENCE)
        source = source_map.get(agent_type, SourceType.MODEL_INFERENCE)
        confidence = 0.9 if agent_type == "data" else 0.75

        citation_objs: list[Citation] = []
        for i, c in enumerate(citations or []):
            citation_objs.append(
                Citation(
                    id=str(c.get("id") or f"c{i+1}"),
                    source_type=source,
                    source_name=str(c.get("title") or c.get("source") or "来源"),
                    content_snippet=str(c.get("snippet") or c.get("content") or ""),
                    url=c.get("url"),
                )
            )

        if not citation_objs and agent_type == "data":
            q = str(metadata.get("query") or "")
            if q:
                citation_objs.append(
                    Citation(
                        id="db_query",
                        source_type=SourceType.DATABASE,
                        source_name=str(metadata.get("data_source_name") or "数据库"),
                        content_snippet=f"查询: {q[:120]}",
                    )
                )

        anno = EvidenceAnnotation(level=level, source_type=source, citations=citation_objs, confidence=confidence)
        return AnnotatedResponse(fragments=[AnnotatedContent(text=content, annotation=anno)], metadata={"agent_type": agent_type})

    def merge_responses(self, responses: list[AnnotatedResponse]) -> AnnotatedResponse:
        frags = []
        for r in responses:
            frags.extend(r.fragments)
        return AnnotatedResponse(fragments=frags, metadata={"merged_from": len(responses)})

    def annotate_sql_result(
        self,
        sql: str,
        rows: list[dict[str, Any]],
        data_source: str,
        confidence: float,
        row_count: int | None = None,
    ) -> AnnotatedResponse:
        """Generate evidence for SQL query results."""
        rc = row_count if row_count is not None else len(rows)
        citation = Citation(
            id="sql_query",
            source_type=SourceType.DATABASE,
            source_name=data_source,
            content_snippet=sql[:200],
        )
        anno = EvidenceAnnotation(
            level=EvidenceLevel.FACT,
            source_type=SourceType.DATABASE,
            citations=[citation],
            confidence=confidence,
        )
        snippet = f"SQL: {sql} | Rows: {rc}"
        content = AnnotatedContent(text=snippet, annotation=anno)
        return AnnotatedResponse(
            fragments=[content],
            metadata={
                "type": "sql_query_result",
                "sql": sql,
                "data_source": data_source,
                "row_count": rc,
                "confidence": confidence,
            },
        )
