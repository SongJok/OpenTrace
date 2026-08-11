"""从治理逻辑计划确定性编译常见企业指标查询。"""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from typing import Any

from data_agent.contracts import (
    CandidateSQL,
    EvidenceBundle,
    FilterSpec,
    JoinSpec,
    LogicalQueryPlan,
    QueryRequest,
)


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _alias(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "")).strip("_")
    if not normalized or normalized[0].isdigit():
        return fallback
    return normalized[:64]


def _time_literal(value: Any, dialect: str) -> str:
    text = str(value)
    if str(dialect or "").lower() in {"mysql", "doris"}:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            pass
        else:
            text = parsed.strftime("%Y-%m-%d %H:%M:%S")
    return _sql_literal(text)


class DeterministicSQLCompiler:
    """只编译已发布指标、已解析维度和已验证 JOIN 能完整证明的计划。"""

    def compile(
        self,
        request: QueryRequest,
        plan: LogicalQueryPlan,
        evidence: EvidenceBundle,
    ) -> list[CandidateSQL]:
        if not plan.metrics or plan.needs_clarification or plan.comparison:
            return []
        tables = self._required_tables(plan)
        if not tables:
            return []
        joins = self._join_path(tables, plan.joins)
        if len(tables) > 1 and not joins:
            return []

        select_parts: list[str] = []
        group_by: list[str] = []
        for index, dimension in enumerate(plan.dimensions, start=1):
            if not dimension.column:
                return []
            expression = (
                f"{dimension.table}.{dimension.column}" if dimension.table else dimension.column
            )
            select_parts.append(f"{expression} AS {_alias(dimension.name, f'dimension_{index}')}")
            group_by.append(expression)

        time_expression = self._time_dimension(plan, evidence)
        if time_expression:
            select_parts.insert(0, f"{time_expression} AS period")
            group_by.insert(0, time_expression)

        for index, metric in enumerate(plan.metrics, start=1):
            formula = str(metric.formula or "").strip()
            if not formula:
                return []
            select_parts.append(f"{formula} AS {_alias(metric.name, f'metric_{index}')}")

        where_parts: list[str] = []
        for metric in plan.metrics:
            where_parts.extend(
                str(value).strip() for value in metric.required_filters if str(value).strip()
            )
        for item in plan.filters:
            compiled = self._compile_filter(item, evidence)
            if compiled is None:
                return []
            where_parts.append(compiled)
        time_filter = self._time_filter(plan, evidence.dialect)
        if time_filter:
            where_parts.append(time_filter)

        root = tables[0]
        sql_parts = ["SELECT", "  " + ",\n  ".join(select_parts), f"FROM {root}"]
        for join in joins:
            sql_parts.append(
                f"{join.join_type.upper()} JOIN {join.right_table} "
                f"ON {join.left_table}.{join.left_column} = "
                f"{join.right_table}.{join.right_column}"
            )
        if where_parts:
            sql_parts.append("WHERE " + "\n  AND ".join(f"({item})" for item in where_parts))
        if group_by:
            sql_parts.append("GROUP BY " + ", ".join(group_by))
        if plan.intent == "trend" and time_expression:
            sql_parts.append("ORDER BY period ASC")
        elif plan.intent == "ranking":
            metric_alias = _alias(plan.metrics[0].name, "metric_1")
            sql_parts.append(f"ORDER BY {metric_alias} DESC")

        return [
            CandidateSQL(
                sql="\n".join(sql_parts),
                source="semantic_compiler",
                assumptions=[
                    "SQL 由已发布指标公式和已验证关系确定性编译",
                    *plan.assumptions,
                ],
            )
        ]

    @staticmethod
    def _required_tables(plan: LogicalQueryPlan) -> list[str]:
        values: list[str] = []
        for table in plan.required_tables:
            if table and table not in values:
                values.append(table)
        for metric in plan.metrics:
            for column in metric.underlying_columns:
                if "." in column:
                    table = column.rsplit(".", 1)[0]
                    if table and table not in values:
                        values.append(table)
            if metric.time_field and "." in metric.time_field:
                table = metric.time_field.rsplit(".", 1)[0]
                if table and table not in values:
                    values.append(table)
        for dimension in plan.dimensions:
            if dimension.table and dimension.table not in values:
                values.append(dimension.table)
        return values

    @staticmethod
    def _join_path(tables: list[str], candidates: list[JoinSpec]) -> list[JoinSpec]:
        if len(tables) <= 1:
            return []
        verified = [item for item in candidates if item.verified]
        adjacency: dict[str, list[JoinSpec]] = {}
        for item in verified:
            adjacency.setdefault(item.left_table, []).append(item)
            adjacency.setdefault(item.right_table, []).append(
                item.model_copy(
                    update={
                        "left_table": item.right_table,
                        "left_column": item.right_column,
                        "right_table": item.left_table,
                        "right_column": item.left_column,
                    }
                )
            )

        connected = {tables[0]}
        result: list[JoinSpec] = []
        while not set(tables).issubset(connected):
            queue: deque[tuple[str, list[JoinSpec]]] = deque((table, []) for table in connected)
            visited = set(connected)
            found: list[JoinSpec] | None = None
            while queue and found is None:
                current, path = queue.popleft()
                for edge in adjacency.get(current, []):
                    if edge.right_table in visited:
                        continue
                    next_path = [*path, edge]
                    if edge.right_table in tables and edge.right_table not in connected:
                        found = next_path
                        break
                    visited.add(edge.right_table)
                    queue.append((edge.right_table, next_path))
            if not found:
                return []
            for edge in found:
                if edge.right_table not in connected:
                    result.append(edge)
                    connected.add(edge.right_table)
        return result

    @staticmethod
    def _compile_filter(item: FilterSpec, evidence: EvidenceBundle) -> str | None:
        field = str(item.field or "").strip()
        if not field:
            return None
        known_columns = {
            column.lower(): f"{table}.{column}"
            for table, columns in evidence.table_columns.items()
            for column in columns
        }
        qualified = {
            f"{table}.{column}".lower(): f"{table}.{column}"
            for table, columns in evidence.table_columns.items()
            for column in columns
        }
        resolved = qualified.get(field.lower()) or known_columns.get(field.lower())
        if not resolved:
            return None
        operator = str(item.operator or "=").upper()
        if operator not in {"=", "!=", "<>", ">", ">=", "<", "<=", "LIKE"}:
            return None
        return f"{resolved} {operator} {_sql_literal(item.value)}"

    @staticmethod
    def _time_field(plan: LogicalQueryPlan) -> str | None:
        values = [str(metric.time_field or "").strip() for metric in plan.metrics]
        values = [value for value in values if value]
        if not values or len(set(values)) != 1:
            return None
        return values[0]

    def _time_filter(self, plan: LogicalQueryPlan, dialect: str) -> str | None:
        field = self._time_field(plan)
        start = plan.time_window.get("start")
        end = plan.time_window.get("end")
        if not field or not start or not end:
            return None
        return (
            f"{field} >= {_time_literal(start, dialect)} "
            f"AND {field} < {_time_literal(end, dialect)}"
        )

    def _time_dimension(self, plan: LogicalQueryPlan, evidence: EvidenceBundle) -> str | None:
        if plan.intent != "trend":
            return None
        field = self._time_field(plan)
        if not field:
            return None
        grain = str(plan.time_window.get("grain") or "day")
        dialect = str(evidence.dialect or "").lower()
        if grain == "month":
            if dialect in {"postgres", "postgresql", "pg"}:
                return f"DATE_TRUNC('month', {field})"
            if dialect == "clickhouse":
                return f"toStartOfMonth({field})"
            return f"DATE_FORMAT({field}, '%Y-%m-01')"
        if grain == "year":
            if dialect in {"postgres", "postgresql", "pg"}:
                return f"DATE_TRUNC('year', {field})"
            if dialect == "clickhouse":
                return f"toStartOfYear({field})"
            return f"DATE_FORMAT({field}, '%Y-01-01')"
        return f"DATE({field})"
