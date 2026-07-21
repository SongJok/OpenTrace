"""查询规划器 — 将语义解析结果转为 LogicalPlan（中间表示）。"""

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
    将 SemanticParseResult 转换为 LogicalPlan（方言无关的 IR）。

    使用 LLM 生成逻辑计划结构，然后根据模式验证表/列引用的有效性。
    支持多轮规划与错误反馈的自修正。
    """

    MAX_PLAN_ROUNDS = 2

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
        """从语义解析结果生成 LogicalPlan。"""
        tables = table_names or self._table_names or []
        summary = schema_summary or self._schema_summary
        cols = table_columns or {}

        plan_dict = None
        last_errors: list[str] = []

        for round_idx in range(self.MAX_PLAN_ROUNDS):
            plan_dict = await self._generate_logical_plan(
                query=query,
                semantics=semantics,
                tables=tables,
                schema_summary=summary,
                table_columns=cols,
                previous_errors=last_errors if round_idx > 0 else [],
            )

            if not plan_dict:
                break

            plan = self._build_plan_from_dict(plan_dict, tables, cols)

            # 根据模式验证计划
            issues = self._validate_plan(plan, tables, cols)
            if not issues:
                break

            last_errors = issues

        if not plan_dict:
            return self._fallback_plan(semantics, tables, query, dialect)

        plan = self._build_plan_from_dict(plan_dict, tables, cols)

        # 使用表关系图修正 JOIN 路径
        plan = self._validate_joins(plan, tables)

        # 从语义中应用时间窗口过滤
        if semantics.time_window and semantics.time_window.get("days"):
            days = semantics.time_window["days"]
            plan.filters.append(
                FilterSpec(
                    expr=f"__TIME_FILTER__{days}__",
                    is_having=False,
                )
            )

        # 在元数据中存储时间列提示，供 SQLBuilder 使用
        if semantics.time_window and semantics.time_window.get("column_hint"):
            plan.metadata["time_column"] = semantics.time_window["column_hint"]

        return plan

    async def _generate_logical_plan(
        self,
        query: str,
        semantics: SemanticParseResult,
        tables: list[str],
        schema_summary: str,
        table_columns: dict[str, list[str]],
        previous_errors: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """使用 LLM 生成逻辑计划 JSON。"""
        tables_info = ""
        for table, columns in table_columns.items():
            tables_info += f"- {table}: [{', '.join(columns)}]\n"
        if not tables_info:
            tables_info = f"Tables: {', '.join(tables)}\n"

        metrics_info = (
            ", ".join(f"{m.mention}→{m.mapped_column}({m.agg})" for m in semantics.metrics)
            if semantics.metrics
            else "(none)"
        )
        filters_info = (
            ", ".join(f"{f.field or '?'}{f.operator}{f.value}" for f in semantics.filters)
            if semantics.filters
            else "(none)"
        )

        error_feedback = ""
        if previous_errors:
            error_feedback = "\nPREVIOUS ERRORS TO FIX:\n" + "\n".join(
                f"- {e}" for e in previous_errors
            )

        prompt = (
            "You are a query planner. Convert the user question and semantic analysis into a "
            "LOGICAL QUERY PLAN (not SQL). Output ONLY a JSON object.\n\n"
            "Rules:\n"
            "- ONLY use table names listed in Available tables\n"
            "- ONLY use column names listed under each table\n"
            "- If a column is not listed, do not use it\n"
            "- All projections must reference valid columns\n"
            "- JOIN on_clause must reference columns from both tables\n"
            f"{error_feedback}"
            "\nRequired JSON structure:\n"
            "{\n"
            '  "tables": ["table_name or table_name alias"],\n'
            '  "joins": [{"left_table": "t1", "right_table": "t2", "join_type": "INNER", "on_clause": "t1.id = t2.ref_id"}],\n'
            '  "projections": [{"expr": "column or AGG(column)", "alias": "name", "agg_func": "SUM/COUNT/AVG/MAX/MIN/"}],\n'
            '  "filters": [{"expr": "column operator value", "is_having": false}],\n'
            '  "group_by": ["column"],\n'
            '  "order_by": [{"expr": "column", "direction": "DESC/ASC"}],\n'
            '  "limit": 100\n'
            "}\n\n"
            f"Available tables:\n{tables_info}"
            f"Schema summary:\n{schema_summary}\n"
            f"User question: {query}\n"
            f"Detected entities: {', '.join(e.mapped_table for e in semantics.entities) or '(none)'}\n"
            f"Detected metrics: {metrics_info}\n"
            f"Detected filters: {filters_info}\n"
            f"Group by intent: {semantics.group_by}\n"
            f"Order by intent: {semantics.order_by}\n"
        )
        try:
            gw = get_model_gateway()
            resp = await gw.complete(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You output ONLY valid JSON objects representing a logical query plan. No SQL. No explanation.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=600,
            )
            raw = (resp.content or "").strip().strip("`").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
            if isinstance(data, dict) and "tables" in data:
                return data
        except Exception:
            pass
        return None

    def _validate_plan(
        self,
        plan: LogicalPlan,
        tables: list[str],
        table_columns: dict[str, list[str]],
    ) -> list[str]:
        """根据可用模式验证 LogicalPlan，返回问题列表。"""
        issues: list[str] = []
        available_tables = set(tables)
        col_map: dict[str, set[str]] = {}
        for t, cols in table_columns.items():
            col_map[t] = set(c.lower() for c in cols)

        # 检查表名是否存在
        for t in plan.tables:
            tname = t.split()[0] if " " in t else t
            if tname not in available_tables:
                issues.append(f"Table '{tname}' not found in available tables")

        # 检查 JOIN 表引用
        for j in plan.joins:
            if j.left_table not in available_tables:
                issues.append(f"Join left table '{j.left_table}' not found")
            if j.right_table not in available_tables:
                issues.append(f"Join right table '{j.right_table}' not found")

        # 检查投影列引用（基础）
        for p in plan.projections:
            if p.expr == "*":
                continue
            col = p.expr.split("(")[-1].rstrip(")").split(".")[-1].lower()
            if col and col not in ("*", "1"):
                found = any(col in col_map.get(t, set()) for t in available_tables)
                if not found and col_map:
                    issues.append(f"Projection column '{col}' not found in any table")

        # 检查 GROUP BY / 聚合一致性
        if plan.group_by:
            non_agg = [p for p in plan.projections if not p.agg_func and p.expr != "*"]
            for p in non_agg:
                col = p.expr.split(".")[-1].lower()
                if col not in (g.lower() for g in plan.group_by):
                    issues.append(f"Non-aggregated column '{p.expr}' not in GROUP BY")

        return issues

    def _build_plan_from_dict(
        self,
        data: dict[str, Any],
        tables: list[str],
        table_columns: dict[str, list[str]],
    ) -> LogicalPlan:
        """将 LLM 输出字典转换为 LogicalPlan。"""
        plan_tables = data.get("tables", [])
        if not plan_tables and tables:
            plan_tables = tables[:3]

        projections: list[Projection] = []
        for p in data.get("projections", []):
            expr = p.get("expr", "")
            if expr:
                projections.append(
                    Projection(
                        expr=expr,
                        alias=p.get("alias", ""),
                        agg_func=p.get("agg_func", ""),
                    )
                )

        joins: list[JoinSpec] = []
        for j in data.get("joins", []):
            joins.append(
                JoinSpec(
                    left_table=j.get("left_table", ""),
                    right_table=j.get("right_table", ""),
                    join_type=j.get("join_type", "INNER"),
                    on_clause=j.get("on_clause", ""),
                )
            )

        filters: list[FilterSpec] = []
        for f in data.get("filters", []):
            expr = f.get("expr", "")
            if expr:
                filters.append(FilterSpec(expr=expr, is_having=f.get("is_having", False)))

        order_by: list[OrderBySpec] = []
        for o in data.get("order_by", []):
            expr = o.get("expr", "")
            if expr:
                order_by.append(
                    OrderBySpec(
                        expr=expr,
                        direction=o.get("direction", "DESC"),
                    )
                )

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
            having=[
                FilterSpec(expr=h.get("expr", "")) for h in data.get("having", []) if h.get("expr")
            ],
        )

    def _fallback_plan(
        self,
        semantics: SemanticParseResult,
        tables: list[str],
        query: str,
        dialect: SQLDialectSpec | None,
    ) -> LogicalPlan:
        """LLM 生成失败时创建后备计划。

        使用已识别的指标和实体构建一个最小但有效的计划，
        而非回退到 SELECT *。
        """
        projections: list[Projection] = []

        # 从检测到的指标构建投影
        for m in semantics.metrics:
            if m.agg and m.mapped_column:
                projections.append(
                    Projection(
                        expr=f"{m.agg}({m.mapped_column})",
                        alias=m.mention,
                        agg_func=m.agg,
                    )
                )

        # 若无指标，尝试实体列
        if not projections:
            for e in semantics.entities:
                if e.mapped_table:
                    projections.append(Projection(expr=f"{e.mapped_table}.*", alias=""))

        # 最后手段：从过滤条件 / 分组提示构建投影
        if not projections and semantics.group_by:
            for g in semantics.group_by:
                projections.append(Projection(expr=g, alias=g))

        if not projections:
            projections.append(Projection(expr="*", alias=""))

        # 从实体确定表
        plan_tables = [e.mapped_table for e in semantics.entities if e.mapped_table]
        if not plan_tables:
            plan_tables = tables[:3] if tables else ["unknown"]

        # 将时间窗口应用到元数据
        metadata: dict[str, Any] = {"fallback": True, "query": query}
        if semantics.time_window and semantics.time_window.get("column_hint"):
            metadata["time_column"] = semantics.time_window["column_hint"]

        return LogicalPlan(
            tables=plan_tables,
            projections=projections,
            filters=[
                FilterSpec(expr=f"{f.field} {f.operator} '{f.value}'")
                for f in semantics.filters
                if f.field
            ],
            group_by=semantics.group_by,
            limit=semantics.limit if semantics.limit else 100,
            metadata=metadata,
        )

    def _validate_joins(self, plan: LogicalPlan, tables: list[str]) -> LogicalPlan:
        """使用表关系图验证并自动填充 JOIN 路径。"""
        if len(plan.tables) < 2 or plan.joins:
            return plan

        table_list = [t.split()[0] if " " in t else t for t in plan.tables]
        join_steps = self._table_graph.find_path_for_tables(table_list)
        if join_steps:
            plan.joins = join_steps
        return plan
