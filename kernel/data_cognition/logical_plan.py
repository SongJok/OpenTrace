"""Logical Plan — intermediate representation (IR) for SQL queries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Projection:
    """A SELECT expression with optional alias."""

    expr: str
    alias: str = ""
    agg_func: str = ""  # SUM, COUNT, AVG, MAX, MIN, COUNT_DISTINCT


@dataclass
class JoinSpec:
    """A JOIN clause."""

    left_table: str
    right_table: str
    join_type: str = "INNER"  # INNER, LEFT, RIGHT
    on_clause: str = ""  # e.g. "o.user_id = u.id"


@dataclass
class FilterSpec:
    """A WHERE/HAVING condition."""

    expr: str
    is_having: bool = False  # True for post-aggregation filters


@dataclass
class OrderBySpec:
    """An ORDER BY clause entry."""

    expr: str
    direction: str = "DESC"  # ASC, DESC


@dataclass
class LogicalPlan:
    """
    Dialect-independent logical query plan.

    This is the core intermediate representation (IR) between semantic parsing
    and SQL generation. LLM produces this structure, not raw SQL strings.
    """

    tables: list[str] = field(default_factory=list)  # [(table, alias), ...] stored as "table alias"
    joins: list[JoinSpec] = field(default_factory=list)
    projections: list[Projection] = field(default_factory=list)
    filters: list[FilterSpec] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    order_by: list[OrderBySpec] = field(default_factory=list)
    limit: int = 100
    having: list[FilterSpec] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables": self.tables,
            "joins": [
                {
                    "left_table": j.left_table,
                    "right_table": j.right_table,
                    "join_type": j.join_type,
                    "on_clause": j.on_clause,
                }
                for j in self.joins
            ],
            "projections": [
                {"expr": p.expr, "alias": p.alias, "agg_func": p.agg_func} for p in self.projections
            ],
            "filters": [{"expr": f.expr, "is_having": f.is_having} for f in self.filters],
            "group_by": self.group_by,
            "order_by": [{"expr": o.expr, "direction": o.direction} for o in self.order_by],
            "limit": self.limit,
            "having": [{"expr": h.expr} for h in self.having],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LogicalPlan:
        joins = [
            JoinSpec(
                left_table=j.get("left_table", ""),
                right_table=j.get("right_table", ""),
                join_type=j.get("join_type", "INNER"),
                on_clause=j.get("on_clause", ""),
            )
            for j in data.get("joins", [])
        ]
        projections = [
            Projection(
                expr=p.get("expr", ""),
                alias=p.get("alias", ""),
                agg_func=p.get("agg_func", ""),
            )
            for p in data.get("projections", [])
        ]
        filters = [
            FilterSpec(expr=f.get("expr", ""), is_having=f.get("is_having", False))
            for f in data.get("filters", [])
        ]
        order_by = [
            OrderBySpec(expr=o.get("expr", ""), direction=o.get("direction", "DESC"))
            for o in data.get("order_by", [])
        ]
        having = [
            FilterSpec(expr=h.get("expr", ""), is_having=True) for h in data.get("having", [])
        ]
        return cls(
            tables=data.get("tables", []),
            joins=joins,
            projections=projections,
            filters=filters,
            group_by=data.get("group_by", []),
            order_by=order_by,
            limit=data.get("limit", 100),
            having=having,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, raw: str) -> LogicalPlan:
        return cls.from_dict(json.loads(raw))

    def validate(
        self, available_tables: set[str], available_columns: dict[str, set[str]]
    ) -> list[str]:
        """Validate plan against available schema. Returns list of issues."""
        issues: list[str] = []

        # Check all referenced tables exist
        for t in self.tables:
            table_name = t.split()[0] if " " in t else t
            if table_name not in available_tables:
                issues.append(f"Table '{table_name}' not found in schema")

        # Check join references
        for j in self.joins:
            if j.left_table not in available_tables:
                issues.append(f"Join left table '{j.left_table}' not found")
            if j.right_table not in available_tables:
                issues.append(f"Join right table '{j.right_table}' not found")

        return issues
