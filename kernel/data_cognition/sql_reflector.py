"""SQL Reflector — post-execution validation and reflection loop."""

from __future__ import annotations

from typing import Any

from kernel.data_cognition.sql_dialect import SQLDialectSpec
from kernel.data_cognition.sql_rewriter import SQLRewriter
from kernel.data_cognition.types import SemanticContext, ValidationResult


class SQLReflector:
    MAX_REFLECTION_ROUNDS = 2

    def __init__(self) -> None:
        self._rewriter = SQLRewriter()

    def validate_result(
        self,
        sql: str,
        rows: list[Any],
        query: str,
        semantic_ctx: SemanticContext | None = None,
    ) -> ValidationResult:
        issues: list[str] = []

        # Non-empty check
        if not rows:
            issues.append("query returned 0 rows — may indicate incorrect filtering or no matching data")

        # Null value check for first row
        if rows:
            first = rows[0] if isinstance(rows, list) else None
            if isinstance(first, dict):
                for k, v in first.items():
                    if v is None:
                        issues.append(f"column '{k}' returned NULL")

        # Numeric range sanity check
        if rows and len(rows) == 1 and isinstance(rows[0], dict):
            for k, v in rows[0].items():
                if isinstance(v, (int, float)) and v < 0:
                    issues.append(f"column '{k}' returned negative value ({v}) — may be anomalous")
                if isinstance(v, (int, float)) and v > 1_000_000_000:
                    issues.append(f"column '{k}' returned extremely large value ({v}) — possible cartesian product")

        # Time consistency check
        if semantic_ctx and semantic_ctx.time_macros:
            for tm in semantic_ctx.time_macros:
                col = tm.get("column", "")
                if col and not _sql_references_column(sql, col):
                    issues.append(f"time filter on '{col}' may be missing from SQL")

        severity = "warning" if issues else "info"
        return ValidationResult(passed=len(issues) == 0, issues=issues, severity=severity)

    async def reflect(
        self,
        sql: str,
        validation: ValidationResult,
        query: str,
        schema_hint: str = "",
        dialect: SQLDialectSpec | None = None,
    ) -> str:
        error_summary = "; ".join(validation.issues)
        return await self._rewriter.rewrite(sql, error_summary, schema_hint, dialect)


def _sql_references_column(sql: str, column: str) -> bool:
    return column.lower() in sql.lower()
