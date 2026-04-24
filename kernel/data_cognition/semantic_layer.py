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
        """Heuristic time intent extraction when semantic config is sparse."""
        patterns = [
            (r"最近\s*(\d+)\s*个?[月天日]", "days", {"月": 30, "天": 1, "日": 1}),
            (r"近\s*(\d+)\s*个?[月天日]", "days", {"月": 30, "天": 1, "日": 1}),
            (r"过去\s*(\d+)\s*个?[月天日]", "days", {"月": 30, "天": 1, "日": 1}),
            (r"last\s+(\d+)\s+(day|week|month)s?", "days", {"day": 1, "week": 7, "month": 30}),
            (r"最近一周", "days_fixed", 7),
            (r"最近一个月", "days_fixed", 30),
            (r"近一个月", "days_fixed", 30),
            (r"近一周", "days_fixed", 7),
        ]
        for pattern, mode, unit_map in patterns:
            m = re.search(pattern, query)
            if not m:
                continue
            if mode == "days_fixed":
                return {"type": "time_window", "days": unit_map, "column": None}
            n = int(m.group(1))
            unit = m.group(2) if m.lastindex and m.lastindex >= 2 else "天"
            days = n * (unit_map.get(unit, 1) if isinstance(unit_map, dict) else 1)
            return {"type": "time_window", "days": days, "column": None}
        return None
