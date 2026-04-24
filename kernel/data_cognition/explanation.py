"""Query Explanation — builds human-readable explanations of executed queries."""

from __future__ import annotations

from typing import Any

from kernel.data_cognition.logical_plan import LogicalPlan
from kernel.data_cognition.types import Explanation


def build_explanation(
    plan: LogicalPlan,
    sql: str,
    rows: list[dict[str, Any]],
    query: str,
    warnings: list[str] | None = None,
) -> Explanation:
    """
    Build a human-readable explanation of what the query does.

    Used to provide transparency to the user about:
    - What the system understood from their question
    - Which tables were queried
    - What filters were applied
    - The generated SQL
    - Result summary
    """
    explanation = Explanation(
        understood_query=query,
        sql=sql,
        row_count=len(rows),
        warnings=warnings or [],
    )

    # Tables used
    explanation.tables_used = [
        t.split()[0] if " " in t else t for t in plan.tables
    ]

    # Filters applied
    for f in plan.filters:
        if not f.is_having and f.expr and not f.expr.startswith("__TIME_FILTER__"):
            explanation.filters_applied.append(f.expr)

    # Summary based on projections
    if plan.projections:
        proj_names = [p.alias or p.expr for p in plan.projections[:5]]
        if len(rows) > 0 and rows[0]:
            explanation.summary = (
                f"Returned {len(rows)} row(s) with columns: {', '.join(list(rows[0].keys())[:5])}"
            )
        else:
            explanation.summary = f"No results found. Projecting: {', '.join(proj_names)}"
    else:
        explanation.summary = f"Returned {len(rows)} row(s)"

    return explanation


def format_explanation(exp: Explanation, include_sql: bool = True) -> str:
    """Format explanation as a human-readable string."""
    parts: list[str] = []

    parts.append(f"**理解的问题**: {exp.understood_query}")

    if exp.tables_used:
        parts.append(f"**使用的表**: {', '.join(exp.tables_used)}")

    if exp.filters_applied:
        parts.append(f"**过滤条件**: {'; '.join(exp.filters_applied)}")

    parts.append(f"**返回结果**: {exp.row_count} 行")

    if exp.summary:
        parts.append(f"**摘要**: {exp.summary}")

    if exp.warnings:
        parts.append(f"**警告**: {'; '.join(exp.warnings)}")

    if include_sql and exp.sql:
        parts.append(f"\n**生成的 SQL**:\n```\n{exp.sql}\n```")

    return "\n\n".join(parts)
