"""Query Planner — converts semantic parse results into a LogicalPlan (IR)."""

from __future__ import annotations

import json
from typing import Any

from kernel.data_cognition.logical_plan import (
    FilterSpec,
    JoinSpec,
    LogicalPlan,
    OrderBySpec,
    Projection,
)
from kernel.data_cognition.sql_dialect import SQLDialectSpec
from kernel.data_cognition.table_graph import TableRelationshipGraph
from kernel.data_cognition.types import SemanticParseResult
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


class QueryPlanner:
    """
    Converts a SemanticParseResult into a LogicalPlan (dialect-independent IR).

    Uses LLM to generate the logical plan structure, then validates it against
    the schema to ensure table/column references are valid.
    """

    def __init__(self, table_names: list[str] | None = None, schema_summary: str = "") -> None:
        self._table_names = table_names or []
        self._schema_summary = schema_summary
        self._table_graph = TableRelationshipGraph()

    async def plan(
        self,
        semantics: SemanticParseResult,
        query: str,
        table_names: list[str] | None = None,
        schema_summary: str = "",
        dialect: SQLDialectSpec | None = None,
        table_columns: dict[str, list[str]] | None = None,
    ) -> LogicalPlan:
        """Generate a LogicalPlan from semantic parse result."""
        tables = table_names or self._table_names or []
        summary = schema_summary or self._schema_summary

        # Build context for LLM
        entity_names = [e.mapped_table for e in semantics.entities if e.mapped_table]
        if not entity_names and tables:
            # Use available tables as fallback
            entity_names = tables[:3]

        # LLM-based logical plan generation
        plan_dict = await self._generate_logical_plan(
            query=query,
            semantics=semantics,
            tables=tables,
            schema_summary=summary,
            table_columns=table_columns or {},
        )

        if not plan_dict:
            return self._fallback_plan(semantics, tables, query, dialect)

        # Build LogicalPlan from LLM output
        plan = self._build_plan_from_dict(plan_dict, tables, table_columns or {})

        # Validate and fix join paths
        plan = self._validate_joins(plan, tables)

        # Apply time window filter from semantics
        if semantics.time_window and semantics.time_window.get("days"):
            days = semantics.time_window["days"]
            # Add time filter as a placeholder — SQLBuilder will fill in the exact syntax
            plan.filters.append(FilterSpec(
                expr=f"__TIME_FILTER__{days}__",  # Placeholder, resolved by SQLBuilder
                is_having=False,
            ))

        return plan

    async def _generate_logical_plan(
        self,
        query: str,
        semantics: SemanticParseResult,
        tables: list[str],
        schema_summary: str,
        table_columns: dict[str, list[str]],
    ) -> dict[str, Any] | None:
        """Use LLM to generate a logical plan JSON."""
        tables_info = ""
        for table, columns in table_columns.items():
            tables_info += f"- {table}: {', '.join(columns)}\n"
        if not tables_info:
            tables_info = f"Tables: {', '.join(tables)}\n"

        metrics_info = ", ".join(
            f"{m.mention}→{m.mapped_column}({m.agg})" for m in semantics.metrics
        )
        filters_info = ", ".join(
            f"{f.field}{f.operator}{f.value}" for f in semantics.filters
        )

        prompt = (
            "You are a query planner. Convert the user question and semantic analysis into a "
            "LOGICAL QUERY PLAN (not SQL). Output ONLY a JSON object.\n\n"
            "Required JSON structure:\n"
            '{\n'
            '  "tables": ["table_name or table_name alias"],\n'
            '  "joins": [{"left_table": "t1", "right_table": "t2", "join_type": "INNER", "on_clause": "t1.id = t2.ref_id"}],\n'
            '  "projections": [{"expr": "column or AGG(column)", "alias": "name", "agg_func": "SUM/COUNT/AVG/MAX/MIN/"}],\n'
            '  "filters": [{"expr": "column operator value", "is_having": false}],\n'
            '  "group_by": ["column"],\n'
            '  "order_by": [{"expr": "column", "direction": "DESC/ASC"}],\n'
            '  "limit": 100\n'
            '}\n\n'
            f"Available tables:\n{tables_info}"
            f"Schema summary:\n{schema_summary}\n"
            f"User question: {query}\n"
            f"Detected entities: {', '.join(e.mapped_table for e in semantics.entities)}\n"
            f"Detected metrics: {metrics_info}\n"
            f"Detected filters: {filters_info}\n"
            f"Group by intent: {semantics.group_by}\n"
            f"Order by intent: {semantics.order_by}\n"
        )
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                messages=[
                    LLMMessage(role="system", content="You output ONLY valid JSON objects representing a logical query plan. No SQL. No explanation."),
                    LLMMessage(role="user", content=prompt),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=600,
            )
            raw = (resp.content or "").strip().strip("`").strip()
            # Try to extract JSON from potential markdown fences
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
            if isinstance(data, dict) and "tables" in data:
                return data
        except Exception:
            pass
        return None

    def _build_plan_from_dict(
        self, data: dict[str, Any], tables: list[str], table_columns: dict[str, list[str]],
    ) -> LogicalPlan:
        """Convert LLM output dict into a validated LogicalPlan."""
        # Sanitize tables
        plan_tables = data.get("tables", [])
        if not plan_tables and tables:
            plan_tables = tables[:3]

        # Build projections
        projections: list[Projection] = []
        for p in data.get("projections", []):
            expr = p.get("expr", "")
            if expr:
                projections.append(Projection(
                    expr=expr,
                    alias=p.get("alias", ""),
                    agg_func=p.get("agg_func", ""),
                ))

        # Build joins
        joins: list[JoinSpec] = []
        for j in data.get("joins", []):
            joins.append(JoinSpec(
                left_table=j.get("left_table", ""),
                right_table=j.get("right_table", ""),
                join_type=j.get("join_type", "INNER"),
                on_clause=j.get("on_clause", ""),
            ))

        # Build filters
        filters: list[FilterSpec] = []
        for f in data.get("filters", []):
            expr = f.get("expr", "")
            if expr:
                filters.append(FilterSpec(expr=expr, is_having=f.get("is_having", False)))

        # Build order_by
        order_by: list[OrderBySpec] = []
        for o in data.get("order_by", []):
            expr = o.get("expr", "")
            if expr:
                order_by.append(OrderBySpec(
                    expr=expr, direction=o.get("direction", "DESC"),
                ))

        limit = data.get("limit", 0)
        if not limit or limit > 1000:
            limit = 100

        return LogicalPlan(
            tables=plan_tables,
            joins=joins,
            projections=projections,
            filters=filters,
            group_by=data.get("group_by", []),
            order_by=order_by,
            limit=limit,
            having=[FilterSpec(expr=h.get("expr", "")) for h in data.get("having", []) if h.get("expr")],
        )

    def _fallback_plan(
        self, semantics: SemanticParseResult, tables: list[str], query: str, dialect: SQLDialectSpec | None,
    ) -> LogicalPlan:
        """Create a simple fallback plan when LLM generation fails."""
        projections: list[Projection] = []
        for m in semantics.metrics:
            if m.agg and m.mapped_column:
                projections.append(Projection(
                    expr=f"{m.agg}({m.mapped_column})", alias=m.mention, agg_func=m.agg,
                ))

        if not projections:
            projections.append(Projection(expr="*", alias=""))

        return LogicalPlan(
            tables=tables[:3] if tables else ["unknown"],
            projections=projections,
            limit=semantics.limit if semantics.limit else 100,
            metadata={"fallback": True, "query": query},
        )

    def _validate_joins(self, plan: LogicalPlan, tables: list[str]) -> LogicalPlan:
        """Validate and auto-fill join paths using table relationship graph."""
        if len(plan.tables) < 2 or plan.joins:
            return plan

        # Try to infer join path from table graph
        table_list = [t.split()[0] if " " in t else t for t in plan.tables]
        join_steps = self._table_graph.find_path_for_tables(table_list)
        if join_steps:
            plan.joins = join_steps
        return plan
