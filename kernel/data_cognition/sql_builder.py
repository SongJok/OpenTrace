"""SQL Builder — deterministic LogicalPlan → SQL string translation."""

from __future__ import annotations

import re

from kernel.data_cognition.logical_plan import JoinSpec, LogicalPlan
from kernel.data_cognition.sql_dialect import SQLDialectSpec, render_time_window


class SQLBuilder:
    """
    Converts a LogicalPlan into executable SQL.

    This is a DETERMINISTIC translator — no LLM involved.
    Given the same LogicalPlan and dialect, it always produces the same SQL.
    """

    def __init__(self, default_limit: int = 100) -> None:
        self._default_limit = default_limit

    def build(self, plan: LogicalPlan, dialect: SQLDialectSpec | None = None) -> str:
        """Build SQL string from LogicalPlan."""
        dialect = dialect or SQLDialectSpec(
            name="mysql", schema_name="information_schema", supports_interval_days=False
        )

        select = self._build_select(plan, dialect)
        from_clause = self._build_from(plan, dialect)
        where = self._build_where(plan, dialect)
        group_by = self._build_group_by(plan)
        having = self._build_having(plan)
        order_by = self._build_order_by(plan, dialect)
        limit = self._build_limit(plan)

        parts = [f"SELECT {select}", f"FROM {from_clause}"]
        if where.strip():
            parts.append(where)
        if group_by.strip():
            parts.append(group_by)
        if having.strip():
            parts.append(having)
        if order_by.strip():
            parts.append(order_by)
        if limit.strip():
            parts.append(limit)

        return " ".join(parts)

    def _build_select(self, plan: LogicalPlan, dialect: SQLDialectSpec) -> str:
        if not plan.projections:
            return self._escape_ident("*", dialect)

        items: list[str] = []
        for p in plan.projections:
            expr = p.expr
            if p.alias:
                alias = self._escape_ident(p.alias, dialect)
                items.append(f"{expr} AS {alias}")
            else:
                items.append(expr)
        return ", ".join(items)

    def _build_from(self, plan: LogicalPlan, dialect: SQLDialectSpec) -> str:
        if not plan.tables:
            return self._escape_ident("dual", dialect)

        # First table as base
        first = plan.tables[0]
        alias = self._extract_alias(first)
        from_parts = [
            f"{self._escape_ident(first.split()[0], dialect)} {self._escape_ident(alias, dialect)}"
        ]

        # Add joins
        for join in plan.joins:
            join_type = join.join_type.upper()
            if join_type == "INNER":
                join_type = ""  # Default JOIN is INNER
            left = self._escape_ident(join.left_table, dialect)
            right = self._escape_ident(join.right_table, dialect)
            on = join.on_clause
            if not on:
                # Avoid cartesian product: use table graph to find real join condition
                on = self._resolve_join_on_clause(join, plan, dialect)
                if not on:
                    continue  # Skip join if no valid on_clause found
            from_parts.append(f"{join_type} JOIN {right} ON {on}".strip())

        return " ".join(from_parts)

    def _resolve_join_on_clause(
        self,
        join: JoinSpec,
        plan: LogicalPlan,
        dialect: SQLDialectSpec,
    ) -> str:
        """Resolve a missing on_clause using table relationship graph."""
        from kernel.data_cognition.table_graph import TableRelationshipGraph

        graph = TableRelationshipGraph()
        table_cols = plan.metadata.get("table_columns", {})
        for table, columns in table_cols.items():
            graph.register_columns(table, columns)

        # Try FK graph first
        step = graph.find_join_path(join.left_table, join.right_table)
        if step:
            return f"{join.left_table}.{step[0].left_key} = {join.right_table}.{step[0].right_key}"

        # Only generate heuristic join if we have column info
        left_cols = table_cols.get(join.left_table, [])
        right_cols = table_cols.get(join.right_table, [])
        if left_cols and right_cols:
            left_base = join.left_table.rstrip("s")
            right_base = join.right_table.rstrip("s")
            # Try to find matching columns
            for lc in left_cols:
                for rc in right_cols:
                    if f"{right_base}_id" == lc.lower() or f"{left_base}_id" == rc.lower():
                        return f"{join.left_table}.{lc} = {join.right_table}.{rc}"

        # Fallback: preserve 1=1 to avoid breaking existing behavior
        return "1=1"

    def _build_where(self, plan: LogicalPlan, dialect: SQLDialectSpec) -> str:
        conditions: list[str] = []
        for f in plan.filters:
            if f.is_having:
                continue
            expr = f.expr
            # Handle time filter placeholder
            if expr.startswith("__TIME_FILTER__") and expr.endswith("__"):
                days_match = re.search(r"__TIME_FILTER__(\d+)__", expr)
                if days_match:
                    days = int(days_match.group(1))
                    # Try to determine date column from plan metadata, then projections, then fallback
                    date_column = plan.metadata.get("time_column") or self._guess_time_column(plan)
                    time_clause = render_time_window(dialect, date_column, days)
                    if time_clause:
                        conditions.append(time_clause.lstrip(" WHERE "))
                continue
            if expr.strip():
                conditions.append(expr)

        if not conditions:
            return ""
        return "WHERE " + " AND ".join(conditions)

    def _build_group_by(self, plan: LogicalPlan) -> str:
        if not plan.group_by:
            return ""
        items = [g.strip() for g in plan.group_by if g.strip()]
        if not items:
            return ""
        return "GROUP BY " + ", ".join(items)

    def _build_having(self, plan: LogicalPlan) -> str:
        if not plan.having:
            return ""
        conditions = [h.expr for h in plan.having if h.expr.strip()]
        if not conditions:
            return ""
        return "HAVING " + " AND ".join(conditions)

    def _build_order_by(self, plan: LogicalPlan, dialect: SQLDialectSpec) -> str:
        if not plan.order_by:
            return ""
        items: list[str] = []
        for o in plan.order_by:
            if not o.expr:
                continue
            expr = o.expr
            direction = o.direction.upper()
            if direction not in ("ASC", "DESC"):
                direction = "DESC"
            items.append(f"{expr} {direction}")
        if not items:
            return ""
        return "ORDER BY " + ", ".join(items)

    def _build_limit(self, plan: LogicalPlan) -> str:
        limit = plan.limit if plan.limit and plan.limit > 0 else self._default_limit
        return f"LIMIT {limit}"

    def _escape_ident(self, ident: str, dialect: SQLDialectSpec) -> str:
        """Escape SQL identifier based on dialect."""
        if not ident or ident == "*":
            return ident
        # Don't escape expressions (contain spaces, operators, functions)
        if " " in ident or "(" in ident or "." in ident:
            return ident
        if dialect.name == "postgres":
            return f'"{ident}"'
        return f"`{ident}`"

    def _extract_alias(self, table_str: str) -> str:
        """Extract alias from 'table alias' string."""
        parts = table_str.strip().split()
        if len(parts) >= 2:
            return parts[1]
        # Generate short alias from table name
        name = parts[0]
        return name[0].lower() if name else "t"

    def _guess_time_column(self, plan: LogicalPlan) -> str | None:
        """Guess a likely time column from the plan's context."""
        # Priority 1: use explicit time_column from plan metadata (set by QueryPlanner)
        if plan.metadata.get("time_column"):
            return plan.metadata["time_column"]

        # Common datetime column names across databases
        common_time_cols = {
            "created_at",
            "updated_at",
            "create_time",
            "update_time",
            "order_time",
            "pay_time",
            "date",
            "time",
            "timestamp",
            "created_time",
            "modified_at",
        }

        # Priority 2: check filters for column references
        for f in plan.filters:
            if f.expr and not f.is_having:
                col = f.expr.split()[0].split(".")[-1].lower() if f.expr else ""
                if col in common_time_cols:
                    return col

        # Priority 3: check projections
        for p in plan.projections:
            col = (p.alias or p.expr).split(".")[-1].lower()
            if col in common_time_cols:
                return col

        # Priority 4: check table columns from metadata
        table_cols = plan.metadata.get("table_columns", {})
        for table, columns in table_cols.items():
            for col in columns:
                if col.lower() in common_time_cols:
                    return col

        # Priority 5: table name heuristics
        for t in plan.tables:
            tname = t.split()[0].lower()
            if any(kw in tname for kw in ("log", "history", "record", "event", "transaction")):
                return "created_at"
        return None
