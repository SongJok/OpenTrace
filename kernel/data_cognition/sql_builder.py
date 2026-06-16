"""SQL 构建器 — 确定性 LogicalPlan → SQL 字符串。"""

from __future__ import annotations

import re

from kernel.data_cognition.logical_plan import JoinSpec, LogicalPlan
from kernel.data_cognition.sql_dialect import SQLDialectSpec, render_time_window


class SQLBuilder:
    """
    将 LogicalPlan 转为可执行 SQL。

    确定性翻译器，不调用 LLM；相同 LogicalPlan 与方言始终产出相同 SQL。
    """

    def __init__(self, default_limit: int = 100) -> None:
        self._default_limit = default_limit

    def build(self, plan: LogicalPlan, dialect: SQLDialectSpec | None = None) -> str:
        """由 LogicalPlan 生成 SQL 字符串。"""
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

        # 第一个表作为基础
        first = plan.tables[0]
        alias = self._extract_alias(first)
        from_parts = [
            f"{self._escape_ident(first.split()[0], dialect)} {self._escape_ident(alias, dialect)}"
        ]

        # 添加 JOIN
        for join in plan.joins:
            join_type = join.join_type.upper()
            if join_type == "INNER":
                join_type = ""  # 默认 JOIN 为 INNER
            left = self._escape_ident(join.left_table, dialect)
            right = self._escape_ident(join.right_table, dialect)
            on = join.on_clause
            if not on:
                # 避免笛卡尔积：使用表关系图查找真实 JOIN 条件
                on = self._resolve_join_on_clause(join, plan, dialect)
                if not on:
                    continue  # 跳过无有效 on_clause 的 JOIN
            from_parts.append(f"{join_type} JOIN {right} ON {on}".strip())

        return " ".join(from_parts)

    def _resolve_join_on_clause(
        self,
        join: JoinSpec,
        plan: LogicalPlan,
        dialect: SQLDialectSpec,
    ) -> str:
        """使用表关系图解析缺失的 on_clause。"""
        from kernel.data_cognition.table_graph import TableRelationshipGraph

        graph = TableRelationshipGraph()
        table_cols = plan.metadata.get("table_columns", {})
        for table, columns in table_cols.items():
            graph.register_columns(table, columns)

        # 优先尝试外键图
        step = graph.find_join_path(join.left_table, join.right_table)
        if step:
            return f"{join.left_table}.{step[0].left_key} = {join.right_table}.{step[0].right_key}"

        # 仅在有列信息时生成启发式 JOIN
        left_cols = table_cols.get(join.left_table, [])
        right_cols = table_cols.get(join.right_table, [])
        if left_cols and right_cols:
            left_base = join.left_table.rstrip("s")
            right_base = join.right_table.rstrip("s")
            # 尝试查找匹配的列
            for lc in left_cols:
                for rc in right_cols:
                    if f"{right_base}_id" == lc.lower() or f"{left_base}_id" == rc.lower():
                        return f"{join.left_table}.{lc} = {join.right_table}.{rc}"

        # 回退：保留 1=1 以避免破坏现有行为
        return "1=1"

    def _build_where(self, plan: LogicalPlan, dialect: SQLDialectSpec) -> str:
        conditions: list[str] = []
        for f in plan.filters:
            if f.is_having:
                continue
            expr = f.expr
            # 处理时间过滤占位符
            if expr.startswith("__TIME_FILTER__") and expr.endswith("__"):
                days_match = re.search(r"__TIME_FILTER__(\d+)__", expr)
                if days_match:
                    days = int(days_match.group(1))
                    # 尝试从计划元数据确定日期列，然后从投影，最后回退
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
        """根据方言转义 SQL 标识符。"""
        if not ident or ident == "*":
            return ident
        # 不转义表达式（包含空格、运算符、函数）
        if " " in ident or "(" in ident or "." in ident:
            return ident
        if dialect.name == "postgres":
            return f'"{ident}"'
        return f"`{ident}`"

    def _extract_alias(self, table_str: str) -> str:
        """从 '表 别名' 字符串中提取别名。"""
        parts = table_str.strip().split()
        if len(parts) >= 2:
            return parts[1]
        # 从表名生成短别名
        name = parts[0]
        return name[0].lower() if name else "t"

    def _guess_time_column(self, plan: LogicalPlan) -> str | None:
        """从计划上下文中猜测可能的时间列。"""
        # 优先级 1：使用计划元数据中的显式 time_column（由 QueryPlanner 设置）
        if plan.metadata.get("time_column"):
            return plan.metadata["time_column"]

        # 常见日期时间列名
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

        # 优先级 2：检查过滤器中的列引用
        for f in plan.filters:
            if f.expr and not f.is_having:
                col = f.expr.split()[0].split(".")[-1].lower() if f.expr else ""
                if col in common_time_cols:
                    return col

        # 优先级 3：检查投影
        for p in plan.projections:
            col = (p.alias or p.expr).split(".")[-1].lower()
            if col in common_time_cols:
                return col

        # 优先级 4：检查元数据中的表列
        table_cols = plan.metadata.get("table_columns", {})
        for table, columns in table_cols.items():
            for col in columns:
                if col.lower() in common_time_cols:
                    return col

        # 优先级 5：表名启发式
        for t in plan.tables:
            tname = t.split()[0].lower()
            if any(kw in tname for kw in ("log", "history", "record", "event", "transaction")):
                return "created_at"
        return None
