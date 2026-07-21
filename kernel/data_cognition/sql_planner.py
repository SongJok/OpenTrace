from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.data_cognition.sql_dialect import SQLDialectSpec
from kernel.data_cognition.table_graph import TableRelationshipGraph
from kernel.data_cognition.types import CandidateSQL
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway


@dataclass
class PlannedSQL:
    sql: str
    join_path: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SQLPlanner:
    def __init__(self) -> None:
        self.table_graph = TableRelationshipGraph()

    async def plan(
        self, question: str, schema_hint: str = "", dialect: SQLDialectSpec | None = None
    ) -> PlannedSQL:
        dialect_name = dialect.name if dialect else "generic"
        prompt = (
            "You are a senior Text2SQL planner. Generate a single safe SQL query. "
            "Only output SQL. Use SELECT/WITH only and include LIMIT. "
            "If the user asks about multiple entities/tables, infer JOIN paths from the schema hint. "
            f"Target dialect: {dialect_name}."
        )
        user = f"Question: {question}\nSchema hint: {schema_hint}\nDialect: {dialect_name}"
        gw = get_model_gateway()
        resp = await gw.complete(
            messages=[
                LLMMessage(role="system", content=prompt),
                LLMMessage(role="user", content=user),
            ],
            role=LLMRole.PLANNING,
            temperature=0.0,
            max_tokens=300,
        )
        sql = (resp.content or "").strip().strip("`")
        tables = self.table_graph.infer_tables_from_schema_hint(schema_hint)
        join_steps = self.table_graph.find_path_for_tables(tables)
        join_path = [
            f"{step.left_table}.{step.left_key}={step.right_table}.{step.right_key}"
            for step in join_steps
        ]
        if join_path:
            sql = self._ensure_join_metadata(sql, join_path)
        return PlannedSQL(
            sql=sql, join_path=join_path, metadata={"dialect": dialect_name, "tables": tables}
        )

    async def generate_candidates(
        self,
        question: str,
        schema_hint: str = "",
        dialect: SQLDialectSpec | None = None,
        n: int = 4,
        semantic_fragments: list[str] | None = None,
    ) -> list[CandidateSQL]:
        """Generate multiple candidate SQL statements via varied sampling."""
        dialect_name = dialect.name if dialect else "generic"
        fragment_hint = ""
        if semantic_fragments:
            fragment_hint = "\nSemantic hints: " + " | ".join(semantic_fragments)

        templates = [
            (
                "You are a senior Text2SQL planner. Generate a safe, efficient SQL query. "
                "Only output SQL. Use SELECT/WITH only and include LIMIT. "
                f"Target dialect: {dialect_name}.{fragment_hint}"
            ),
            (
                f"Generate a SQL query for this question using {dialect_name} dialect. "
                "Output ONLY the SQL statement, no explanation. Must be read-only with LIMIT. "
                "Prefer explicit JOIN syntax and COUNT(DISTINCT ...) for aggregations."
                + (f" Apply these constraints: {fragment_hint}" if fragment_hint else "")
            ),
            (
                "Write a read-only SQL query answering the question below. "
                "Use proper dialect syntax. Include LIMIT clause. "
                "Output nothing else."
                + (f" Business context: {fragment_hint}" if fragment_hint else "")
            ),
        ]

        candidates: list[CandidateSQL] = []
        gw = get_model_gateway()
        seen: set[str] = set()

        for i in range(n):
            template = templates[i % len(templates)]
            temp = 0.3 if i < 2 else 0.7  # mix of low and higher temperature
            user = f"Question: {question}\nSchema hint: {schema_hint}\nDialect: {dialect_name}"

            resp = await gw.complete(
                messages=[
                    LLMMessage(role="system", content=template),
                    LLMMessage(role="user", content=user),
                ],
                role=LLMRole.PLANNING,
                temperature=temp,
                max_tokens=400,
            )
            sql = (resp.content or "").strip().strip("`").strip()
            if not sql or sql.lower() in seen:
                continue
            seen.add(sql.lower())

            tables = self.table_graph.infer_tables_from_schema_hint(schema_hint)
            join_steps = self.table_graph.find_path_for_tables(tables)
            join_path = [
                f"{step.left_table}.{step.left_key}={step.right_table}.{step.right_key}"
                for step in join_steps
            ]

            candidates.append(
                CandidateSQL(
                    sql=sql,
                    features={
                        "dialect": dialect_name,
                        "temperature": temp,
                        "template_idx": i % len(templates),
                        "join_depth": len(join_steps),
                    },
                    source_template=template[:60],
                )
            )

        if not candidates:
            # Fallback: single deterministic generation
            planned = await self.plan(question, schema_hint, dialect)
            if planned.sql:
                candidates.append(CandidateSQL(sql=planned.sql, source_template="fallback_plan"))

        return candidates

    def _ensure_join_metadata(self, sql: str, join_path: list[str]) -> str:
        if not sql:
            return sql
        return sql + f"\n-- join_path: {' | '.join(join_path)}"
