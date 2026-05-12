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

    def __init__(
        self,
        schema_summary: str = "",
        table_names: list[str] | None = None,
        table_columns: dict[str, list[str]] | None = None,
        column_synonyms: dict[str, list[str]] | None = None,
    ) -> None:
        self._schema_summary = schema_summary or ""
        self._table_names = table_names or []
        self._table_columns = table_columns or {}
        self._column_synonyms = column_synonyms or {}
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
        self,
        query: str,
        table_columns: dict[str, list[str]] | None = None,
    ) -> list[EntityMapping]:
        """Map natural language mentions in query to database tables."""
        entities: list[EntityMapping] = []
        query_lower = query.lower()
        cols = table_columns or self._table_columns

        # Rule-based table matching first
        for table in self._table_names:
            if table.lower() in query_lower or _fuzzy_table_match(table, query):
                entities.append(EntityMapping(mention=table, mapped_table=table, confidence=0.85))

        # If rule-based found nothing, use LLM with full schema context
        if not entities and self._schema_summary:
            entities = await self._llm_link_entities(query, table_columns=cols)

        return entities

    async def link_columns(
        self,
        mention: str,
        table_candidates: list[str] | None = None,
        table_columns: dict[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Map a mention to database columns with similarity scoring.

        Returns list of {table, column, similarity} sorted by score desc.
        """
        results: list[dict[str, Any]] = []
        cols = table_columns or self._table_columns
        candidates = table_candidates or self._table_names
        mention_lower = mention.lower().strip()

        # 1. Exact column name match
        for table in candidates:
            for col in cols.get(table, []):
                if col.lower() == mention_lower:
                    results.append({"table": table, "column": col, "similarity": 1.0})
                elif mention_lower in col.lower() or col.lower() in mention_lower:
                    score = len(mention_lower) / max(len(col), len(mention_lower))
                    results.append(
                        {"table": table, "column": col, "similarity": round(score * 0.7, 2)}
                    )

        # 2. Synonym match
        for syn, standard_name in self._build_synonym_index().items():
            if syn in mention_lower:
                for table in candidates:
                    for col in cols.get(table, []):
                        if (
                            col.lower() == standard_name.lower()
                            or standard_name.lower() in col.lower()
                        ):
                            results.append({"table": table, "column": col, "similarity": 0.85})

        # 3. LLM fallback if no match
        if not results and self._schema_summary:
            results = await self._llm_link_columns(
                mention, table_candidates=candidates, table_columns=cols
            )

        # Sort by similarity descending, deduplicate
        seen = set()
        deduped = []
        for r in sorted(results, key=lambda x: x["similarity"], reverse=True):
            key = (r["table"], r["column"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped

    def _build_synonym_index(self) -> dict[str, str]:
        """Build a flat synonym → standard column name index."""
        index: dict[str, str] = {}
        for standard, synonyms in self._column_synonyms.items():
            for syn in synonyms:
                index[syn.lower()] = standard
        return index

    async def link_metrics(self, query: str) -> list[MetricMapping]:
        """Map metric mentions (销售额, revenue, count, etc.) to column + aggregation."""
        metrics: list[MetricMapping] = []

        metric_patterns = {
            "销售额": ("total_amount", "SUM"),
            "金额": ("amount", "SUM"),
            "订单数": ("id", "COUNT"),
            "订单量": ("id", "COUNT"),
            "订单": ("id", "COUNT"),
            "用户数": ("id", "COUNT"),
            "用户量": ("id", "COUNT"),
            "平均": ("", "AVG"),
            "总数": ("", "COUNT"),
            "合计": ("", "SUM"),
            "最大": ("", "MAX"),
            "最小": ("", "MIN"),
            "revenue": ("total_amount", "SUM"),
            "sales": ("total_amount", "SUM"),
            "amount": ("amount", "SUM"),
            "total": ("amount", "SUM"),
            "count": ("id", "COUNT"),
            "number": ("id", "COUNT"),
            "average": ("", "AVG"),
            "avg": ("", "AVG"),
            "max": ("", "MAX"),
            "min": ("", "MIN"),
            "profit": ("profit", "SUM"),
            "cost": ("cost", "SUM"),
            "price": ("price", "AVG"),
            "quantity": ("quantity", "SUM"),
            "退款": ("refund_amount", "SUM"),
            "退款率": ("refund_rate", "AVG"),
            "复购": ("repurchase_count", "COUNT"),
            "复购率": ("repurchase_rate", "AVG"),
            "销量": ("quantity", "SUM"),
            "客单价": ("amount", "AVG"),
            "转化率": ("conversion_rate", "AVG"),
            "毛利率": ("margin_rate", "AVG"),
        }
        query_lower = query.lower()
        # Sort by length descending to match longer phrases first
        for mention in sorted(metric_patterns.keys(), key=len, reverse=True):
            if mention.lower() in query_lower:
                col, agg = metric_patterns[mention]
                metrics.append(MetricMapping(mention=mention, mapped_column=col, agg=agg))

        if not metrics:
            metrics = await self._llm_link_metrics(query)

        return metrics

    async def _llm_link_entities(
        self,
        query: str,
        table_columns: dict[str, list[str]] | None = None,
    ) -> list[EntityMapping]:
        """Use LLM to link entities when rules fail, with full schema context."""
        cols = table_columns or self._table_columns
        schema_context = _format_schema_context(self._table_names, cols)

        prompt = (
            "You are a schema linking assistant. Given a user question and available database tables "
            "with their columns, identify which tables the user is referring to. "
            "Output ONLY a JSON array of objects with keys: "
            '"mention" (the user term), "mapped_table" (table name), "confidence" (0-1).\n\n'
            f"Available schema:\n{schema_context}\n"
            f"Question: {query}"
        )
        return await _call_llm_json_array(
            prompt,
            EntityMapping,
            [
                ("mention", str),
                ("mapped_table", str),
                ("confidence", float),
            ],
            primary_field="mention",
        )

    async def _llm_link_columns(
        self,
        mention: str,
        table_candidates: list[str] | None,
        table_columns: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """Use LLM to find matching columns for a mention."""
        cols = {t: table_columns.get(t, []) for t in (table_candidates or self._table_names)}
        schema_context = _format_schema_context(list(cols.keys()), cols)

        prompt = (
            "Given a user term and available database columns, find the best matching column(s). "
            'Output ONLY a JSON array of objects with: "table", "column", "similarity" (0-1).\n\n'
            f"Schema:\n{schema_context}\n"
            f"User term: {mention}"
        )
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                messages=[
                    LLMMessage(
                        role="system", content="You output ONLY valid JSON arrays. No explanation."
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=200,
            )
            raw = _clean_json_response(resp.content)
            data = json.loads(raw)
            if isinstance(data, list):
                return [
                    {
                        "table": e.get("table", ""),
                        "column": e.get("column", ""),
                        "similarity": float(e.get("similarity", 0.5)),
                    }
                    for e in data
                    if e.get("column")
                ]
        except Exception:
            pass
        return []

    async def _llm_link_metrics(self, query: str) -> list[MetricMapping]:
        """Use LLM to link metric mentions to columns."""
        schema_context = _format_schema_context(self._table_names, self._table_columns)

        prompt = (
            "Given a user question and database schema, identify metrics (aggregations) mentioned. "
            'Output ONLY a JSON array with: "mention", "mapped_column", "agg" (SUM/COUNT/AVG/MAX/MIN).\n\n'
            f"Schema:\n{schema_context}\n"
            f"Question: {query}"
        )
        return await _call_llm_json_array(
            prompt,
            MetricMapping,
            [
                ("mention", str),
                ("mapped_column", str),
                ("agg", str),
            ],
            primary_field="mention",
        )

    def infer_join_path(self, tables: list[str]) -> list[str]:
        """Infer join path between tables using foreign key graph."""
        if len(tables) < 2:
            return []
        steps = self._table_graph.find_path_for_tables(tables)
        return [f"{s.left_table}.{s.left_key}={s.right_table}.{s.right_key}" for s in steps]


def _format_schema_context(table_names: list[str], table_columns: dict[str, list[str]]) -> str:
    """Format schema info into a readable context string for LLM prompts."""
    lines = []
    for table in table_names:
        cols = table_columns.get(table, [])
        if cols:
            lines.append(f"Table '{table}': columns = [{', '.join(cols)}]")
        else:
            lines.append(f"Table '{table}'")
    return "\n".join(lines) if lines else f"Tables: {', '.join(table_names)}"


def _clean_json_response(content: str | None) -> str:
    """Clean LLM response to extract raw JSON."""
    raw = (content or "").strip()
    # Strip markdown code fences
    if raw.startswith("```"):
        lines = raw.split("\n", 1)
        raw = lines[1] if len(lines) > 1 else raw
        raw = raw.rsplit("```", 1)[0].strip()
    # Strip leading/trailing non-JSON chars
    raw = raw.strip("`").strip()
    return raw


async def _call_llm_json_array(
    prompt: str,
    result_cls: type,
    fields: list[tuple[str, type]],
    primary_field: str = "mention",
) -> Any:
    """Call LLM for JSON array output with validation and auto-retry."""
    field_defaults = {"str": "", "float": 0.0, "int": 0}
    try:
        gw = get_model_gateway()
        resp = await gw.complete(
            messages=[
                LLMMessage(
                    role="system", content="You output ONLY valid JSON arrays. No explanation."
                ),
                LLMMessage(role="user", content=prompt),
            ],
            role=LLMRole.PLANNING,
            temperature=0.0,
            max_tokens=200,
        )
        raw = _clean_json_response(resp.content)
        data = json.loads(raw)
        if isinstance(data, list):
            results = []
            for e in data:
                if not e.get(primary_field):
                    continue
                kwargs = {}
                for fname, ftype in fields:
                    val = e.get(fname)
                    if val is None:
                        kwargs[fname] = field_defaults.get(ftype.__name__, "")
                    elif ftype is float:
                        kwargs[fname] = float(val)
                    else:
                        kwargs[fname] = val
                results.append(result_cls(**kwargs))
            return results
    except Exception:
        pass
    return []


def _fuzzy_table_match(table_name: str, query: str) -> bool:
    """Fuzzy match table name against query text with reduced false positives."""
    clean = table_name.lower().replace("_", "").replace("-", "")
    query_clean = query.lower().replace("_", "").replace("-", "")
    if clean in query_clean:
        return True
    if len(clean) < 5:
        return False
    prefix = clean[:5]
    idx = query_clean.find(prefix)
    if idx < 0:
        return False
    if idx > 0 and query_clean[idx - 1].isalnum():
        return False
    end = idx + len(prefix)
    if end < len(query_clean) and query_clean[end].isalnum():
        return False
    return True
