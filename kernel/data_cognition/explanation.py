"""查询解释 — 为已执行查询生成可读说明。"""

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
    构建查询功能的可读说明。

    用于向用户提供透明度信息：
    - 系统从用户问题中理解了什么
    - 查询了哪些表
    - 应用了哪些过滤条件
    - 生成的 SQL
    - 结果摘要
    """
    explanation = Explanation(
        understood_query=query,
        sql=sql,
        row_count=len(rows),
        warnings=warnings or [],
    )

    # 使用的表
    explanation.tables_used = [t.split()[0] if " " in t else t for t in plan.tables]

    # 应用的过滤条件
    for f in plan.filters:
        if not f.is_having and f.expr and not f.expr.startswith("__TIME_FILTER__"):
            explanation.filters_applied.append(f.expr)

    # 基于投影的摘要
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
    """将说明格式化为可读字符串。"""
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
