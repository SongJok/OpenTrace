"""Semantic Layer — maps business terminology to database constructs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from kernel.data_cognition.sql_dialect import SQLDialectSpec
from kernel.data_cognition.types import SemanticContext


@dataclass
class DimensionMapping:
    column: str
    table: str = ""
    value_map: dict[str, str] = field(default_factory=dict)
    description: str = ""


@dataclass
class TimeMacroDef:
    pattern: str
    column: str
    table: str = ""
    operator: str = ">="  # >=, <=, between
    days: int = 0
    sql_template: str = ""


class SemanticLayer:
    def __init__(self, semantic_config: dict[str, Any] | None = None) -> None:
        self._config = semantic_config or {}
        self._dimensions: dict[str, DimensionMapping] = {}
        self._metrics: dict[str, str] = {}
        self._time_macros: list[TimeMacroDef] = []
        self._load_config()

    def _load_config(self) -> None:
        for dim_name, dim_cfg in self._config.get("dimensions", {}).items():
            self._dimensions[dim_name] = DimensionMapping(
                column=str(dim_cfg.get("column", "")),
                table=str(dim_cfg.get("table", "")),
                value_map=dict(dim_cfg.get("value_map", {})),
                description=str(dim_cfg.get("description", "")),
            )
        self._metrics = dict(self._config.get("metrics", {}))
        for tm in self._config.get("time_macros", []):
            self._time_macros.append(
                TimeMacroDef(
                    pattern=str(tm["pattern"]),
                    column=str(tm["column"]),
                    table=str(tm.get("table", "")),
                    operator=str(tm.get("operator", ">=")),
                    days=int(tm.get("days", 0)),
                    sql_template=str(tm.get("sql_template", "")),
                )
            )

    def resolve(self, query: str, dialect: SQLDialectSpec | None = None) -> SemanticContext:
        ctx = SemanticContext()
        ctx.dimension_mappings = self._resolve_dimensions(query)
        ctx.metric_defs = self._resolve_metrics(query)
        ctx.time_macros = self._resolve_time_macros(query, dialect)
        ctx.resolved_sql_fragments = self._build_sql_fragments(ctx, dialect)
        return ctx

    def _resolve_dimensions(self, query: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name, dim in self._dimensions.items():
            if name not in query:
                continue
            mapped_values: list[str] = []
            for biz_val, db_val in dim.value_map.items():
                if biz_val in query:
                    mapped_values.append(f"{dim.column} = '{db_val}'")
            if mapped_values or dim.column:
                result[name] = {
                    "column": dim.column,
                    "table": dim.table,
                    "conditions": mapped_values,
                }
        return result

    def _resolve_metrics(self, query: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, sql in self._metrics.items():
            if name in query:
                result[name] = sql
        return result

    def _resolve_time_macros(self, query: str, dialect: SQLDialectSpec | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for tm in self._time_macros:
            if tm.pattern not in query:
                continue
            if tm.sql_template:
                sql = tm.sql_template
            else:
                sql = self._build_time_filter(tm, dialect)
            results.append({
                "pattern": tm.pattern,
                "column": tm.column,
                "table": tm.table,
                "sql": sql,
            })
        return results

    def _build_time_filter(self, tm: TimeMacroDef, dialect: SQLDialectSpec | None) -> str:
        col = tm.column
        days = tm.days
        if dialect is None:
            return f" WHERE {col} >= NOW() - INTERVAL '{days} days'"
        if dialect.name == "postgres":
            return f" WHERE {col} >= NOW() - INTERVAL '{days} days'"
        if dialect.name in {"clickhouse", "doris"}:
            return f" WHERE {col} >= now() - INTERVAL {days} DAY"
        return f" WHERE {col} >= DATE_SUB(NOW(), INTERVAL {days} DAY)"

    def _build_sql_fragments(self, ctx: SemanticContext, dialect: SQLDialectSpec | None) -> list[str]:
        fragments: list[str] = []
        for dim_name, info in ctx.dimension_mappings.items():
            for cond in info.get("conditions", []):
                fragments.append(cond)
        for tm in ctx.time_macros:
            if tm.get("sql"):
                fragments.append(tm["sql"].strip())
        for metric_name, sql in ctx.metric_defs.items():
            fragments.append(sql)
        return fragments

    @staticmethod
    def extract_time_intent(query: str) -> dict[str, Any] | None:
        """Heuristic time intent extraction when semantic config is sparse.

        Returns:
            {"type": "time_window", "days": N, "column": str|None, "raw": str}
        or for absolute ranges:
            {"type": "date_range", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "column": str|None}
        """
        # Absolute date range: "2024年1月15日到2024年3月20日"
        m = re.search(r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})\s*(?:到|至|~|-)\s*(\d{4})[年-](\d{1,2})[月-](\d{1,2})", query)
        if m:
            return {
                "type": "date_range",
                "start": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                "end": f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}",
                "column": None, "raw": m.group(0),
            }

        # Month range: "2024年1月到2024年6月"
        m = re.search(r"(\d{4})[年-](\d{1,2})月\s*(?:到|至|~|-)\s*(\d{4})[年-](\d{1,2})月", query)
        if m:
            import calendar
            start_year, start_month = int(m.group(1)), int(m.group(2))
            end_year, end_month = int(m.group(3)), int(m.group(4))
            _, start_last = calendar.monthrange(start_year, start_month)
            _, end_last = calendar.monthrange(end_year, end_month)
            return {
                "type": "date_range",
                "start": f"{start_year}-{start_month:02d}-01",
                "end": f"{end_year}-{end_month:02d}-{end_last}",
                "column": None, "raw": m.group(0),
            }

        patterns = [
            (r"前\s*(\d+)\s*个?[月天日周]", "days", {"月": 30, "天": 1, "日": 1, "周": 7}),
            (r"最近\s*(\d+)\s*个?[月天日]", "days", {"月": 30, "天": 1, "日": 1}),
            (r"近\s*(\d+)\s*个?[月天日]", "days", {"月": 30, "天": 1, "日": 1}),
            (r"过去\s*(\d+)\s*个?[月天日周]", "days", {"月": 30, "天": 1, "日": 1, "周": 7}),
            (r"last\s+(\d+)\s+(day|week|month)s?", "days", {"day": 1, "week": 7, "month": 30}),
            (r"过去一年", "days_fixed", 365),
            (r"过去半年", "days_fixed", 180),
            (r"最近一周", "days_fixed", 7),
            (r"最近一个月", "days_fixed", 30),
            (r"近一个月", "days_fixed", 30),
            (r"近一周", "days_fixed", 7),
            (r"上个月", "month_offset", -1),
            (r"上月", "month_offset", -1),
        ]
        for pattern, mode, unit_map in patterns:
            m = re.search(pattern, query)
            if not m:
                continue
            if mode == "days_fixed":
                return {"type": "time_window", "days": unit_map, "column": None, "raw": m.group(0)}
            if mode == "month_offset":
                from datetime import datetime
                now = datetime.now()
                month = now.month + unit_map
                year = now.year
                while month < 1:
                    month += 12
                    year -= 1
                while month > 12:
                    month -= 12
                    year += 1
                import calendar
                _, last_day = calendar.monthrange(year, month)
                start = f"{year}-{month:02d}-01"
                end = f"{year}-{month:02d}-{last_day}"
                return {"type": "date_range", "start": start, "end": end, "column": None, "raw": m.group(0)}
            n = int(m.group(1))
            unit = m.group(2) if m.lastindex and m.lastindex >= 2 else "天"
            days = n * (unit_map.get(unit, 1) if isinstance(unit_map, dict) else 1)
            col = SemanticLayer._guess_time_column_from_query(query)
            return {"type": "time_window", "days": days, "column": col, "raw": m.group(0)}

        # Absolute date: "2024年1月" or "2024-01-15"
        m = re.search(r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})", query)
        if m:
            date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return {"type": "date_exact", "start": date_str, "end": date_str, "column": None, "raw": m.group(0)}

        return None

    @staticmethod
    def _guess_time_column_from_query(query: str) -> str | None:
        """Extract a likely time column hint from query text."""
        # Check for explicit column mentions
        time_col_patterns = [
            (r"(?:订单|下单|创建)(?:时|时间|日期)", "order_time"),
            (r"(?:支付|付款|成交)(?:时|时间|日期)", "pay_time"),
            (r"(?:发货|配送)(?:时|时间|日期)", "ship_time"),
            (r"(?:更新|修改)(?:时|时间|日期)", "updated_at"),
            (r"(?:注册| signup)(?:时|时间|日期)", "register_time"),
            (r"(?:登录|访问)(?:时|时间|日期)", "login_time"),
        ]
        for pattern, col in time_col_patterns:
            if re.search(pattern, query):
                return col
        return None
