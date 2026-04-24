"""Schema Linker — maps natural language entities to database tables/columns."""

from __future__ import annotations

import json
from typing import Any

from kernel.data_cognition.table_graph import TableRelationshipGraph
from kernel.data_cognition.types import EntityMapping, MetricMapping
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


class SchemaLinker:
    """Links user mentions to actual database tables and columns."""

    def __init__(self, schema_summary: str = "", table_names: list[str] | None = None) -> None:
        self._schema_summary = schema_summary or ""
        self._table_names = table_names or []
        self._table_graph = TableRelationshipGraph()

    def register_foreign_keys(self, fks: list[dict[str, str]]) -> None:
        """Register foreign key relationships for join path inference."""
        for fk in fks:
            self._table_graph.register_fk(
                left_table=fk.get("table", ""),
                right_table=fk.get("ref_table", ""),
                left_key=fk.get("column", ""),
                right_key=fk.get("ref_column", ""),
            )

    async def link_entities(
        self, query: str, table_columns: dict[str, list[str]] | None = None,
    ) -> list[EntityMapping]:
        """Map natural language mentions in query to database tables."""
        entities: list[EntityMapping] = []
        query_lower = query.lower()

        # Rule-based table matching first
        for table in self._table_names:
            if table.lower() in query_lower or _fuzzy_table_match(table, query):
                entities.append(EntityMapping(mention=table, mapped_table=table, confidence=0.85))

        # If rule-based found nothing, use LLM for entity linking
        if not entities and self._schema_summary:
            entities = await self._llm_link_entities(query)

        return entities

    async def link_metrics(self, query: str) -> list[MetricMapping]:
        """Map metric mentions (销售额, revenue, count, etc.) to column + aggregation."""
        metrics: list[MetricMapping] = []

        # Rule-based common metric patterns (Chinese + English)
        metric_patterns = {
            "销售额": ("total_amount", "SUM"), "金额": ("amount", "SUM"),
            "订单数": ("id", "COUNT"), "订单量": ("id", "COUNT"), "订单": ("id", "COUNT"),
            "用户数": ("id", "COUNT"), "用户量": ("id", "COUNT"),
            "平均": ("", "AVG"), "总数": ("", "COUNT"), "合计": ("", "SUM"),
            "最大": ("", "MAX"), "最小": ("", "MIN"),
            # English metrics
            "revenue": ("total_amount", "SUM"), "sales": ("total_amount", "SUM"),
            "amount": ("amount", "SUM"), "total": ("amount", "SUM"),
            "count": ("id", "COUNT"), "number": ("id", "COUNT"),
            "average": ("", "AVG"), "avg": ("", "AVG"),
            "max": ("", "MAX"), "min": ("", "MIN"),
            "profit": ("profit", "SUM"), "cost": ("cost", "SUM"),
            "price": ("price", "AVG"), "quantity": ("quantity", "SUM"),
        }
        query_lower = query.lower()
        for mention, (col, agg) in metric_patterns.items():
            if mention.lower() in query_lower:
                metrics.append(MetricMapping(mention=mention, mapped_column=col, agg=agg))

        if not metrics:
            metrics = await self._llm_link_metrics(query)

        return metrics

    async def _llm_link_entities(self, query: str) -> list[EntityMapping]:
        """Use LLM to link entities when rules fail."""
        prompt = (
            "You are a schema linking assistant. Given a user question and available database tables, "
            "identify which tables the user is referring to. Output ONLY a JSON array of objects "
            'with keys: "mention" (the user term), "mapped_table" (table name), "confidence" (0-1).\n\n'
            f"Available tables: {', '.join(self._table_names)}\n"
            f"Schema summary:\n{self._schema_summary}\n"
            f"Question: {query}"
        )
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                messages=[
                    LLMMessage(role="system", content="You output ONLY valid JSON arrays. No explanation."),
                    LLMMessage(role="user", content=prompt),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=200,
            )
            raw = (resp.content or "").strip().strip("`").strip()
            data = json.loads(raw)
            if isinstance(data, list):
                return [
                    EntityMapping(
                        mention=e.get("mention", ""),
                        mapped_table=e.get("mapped_table", ""),
                        confidence=float(e.get("confidence", 0.5)),
                    )
                    for e in data
                    if e.get("mapped_table")
                ]
        except Exception:
            pass
        return []

    async def _llm_link_metrics(self, query: str) -> list[MetricMapping]:
        """Use LLM to link metric mentions to columns."""
        prompt = (
            "Given a user question and schema summary, identify metrics (aggregations) mentioned. "
            'Output ONLY JSON array with: "mention", "mapped_column", "agg" (SUM/COUNT/AVG/MAX/MIN).\n\n'
            f"Schema summary:\n{self._schema_summary}\n"
            f"Question: {query}"
        )
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                messages=[
                    LLMMessage(role="system", content="You output ONLY valid JSON arrays. No explanation."),
                    LLMMessage(role="user", content=prompt),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=200,
            )
            raw = (resp.content or "").strip().strip("`").strip()
            data = json.loads(raw)
            if isinstance(data, list):
                return [
                    MetricMapping(
                        mention=m.get("mention", ""),
                        mapped_column=m.get("mapped_column", ""),
                        agg=m.get("agg", ""),
                    )
                    for m in data
                    if m.get("mapped_column") or m.get("agg")
                ]
        except Exception:
            pass
        return []

    def infer_join_path(self, tables: list[str]) -> list[str]:
        """Infer join path between tables using foreign key graph."""
        if len(tables) < 2:
            return []
        steps = self._table_graph.find_path_for_tables(tables)
        return [f"{s.left_table}.{s.left_key}={s.right_table}.{s.right_key}" for s in steps]


def _fuzzy_table_match(table_name: str, query: str) -> bool:
    """Fuzzy match table name against query text with reduced false positives."""
    clean = table_name.lower().replace("_", "").replace("-", "")
    query_clean = query.lower().replace("_", "").replace("-", "")
    # Exact substring match
    if clean in query_clean:
        return True
    # Require at least 5 chars and word-boundary-like match
    # (preceded/followed by non-alphanumeric or start/end of query)
    if len(clean) < 5:
        return False
    prefix = clean[:5]
    idx = query_clean.find(prefix)
    if idx < 0:
        return False
    # Check that the prefix is at a word-like boundary in the query
    if idx > 0 and query_clean[idx - 1].isalnum():
        return False
    # Check the match extends to a reasonable length in the query
    end = idx + len(prefix)
    if end < len(query_clean) and query_clean[end].isalnum():
        return False
    return True
