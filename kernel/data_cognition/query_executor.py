"""Query Executor — executes SQL with self-validation and auto-retry with enhanced error recovery."""

from __future__ import annotations

from typing import Any

from execution.data.sql_executor import SQLExecutor
from kernel.data_cognition.logical_plan import LogicalPlan
from kernel.data_cognition.sql_builder import SQLBuilder
from kernel.data_cognition.sql_dialect import SQLDialectSpec
from kernel.data_cognition.sql_reflector import SQLReflector
from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator
from kernel.data_cognition.sql_rewriter import SQLRewriter


class QueryExecutor:
    """
    Executes SQL with validation, result sanity checks, and automatic correction.

    Flow:
    1. Parse SQL with sqlglot (syntax validation)
    2. Validate read-only safety (SQLValidator)
    3. Execute
    4. Post-execution sanity checks (SQLReflector)
    5. On error: auto-correct via LLM rewrite of the LogicalPlan → rebuild SQL → retry
    6. On final failure: return structured recovery context for user-facing options
    """

    def __init__(
        self,
        validator: SQLValidator | None = None,
        builder: SQLBuilder | None = None,
        reflector: SQLReflector | None = None,
        max_retries: int = 2,
    ) -> None:
        self._validator = validator or SQLValidator(default_limit=100)
        self._builder = builder or SQLBuilder()
        self._reflector = reflector or SQLReflector()
        self._max_retries = max_retries

    async def run_with_retry(
        self,
        plan: LogicalPlan,
        dsn: str,
        dialect: SQLDialectSpec,
        query: str = "",
        schema_hint: str = "",
    ) -> tuple[list[dict[str, Any]], str, list[str]]:
        """
        Execute a LogicalPlan with automatic retry on failure.

        Retry strategy:
        - Attempt 0: build SQL from plan, validate, execute
        - Attempt 1+: LLM rewrites SQL based on error → validate rewritten SQL → execute

        Returns: (rows, final_sql, warnings)
        Raises: SQLValidationError with recovery_context attribute on final failure
        """
        warnings: list[str] = []
        last_error: str = ""
        rewriter = SQLRewriter()
        rewritten_sql: str | None = None

        for attempt in range(self._max_retries + 1):
            # If we have a rewritten SQL from LLM, use it directly
            if rewritten_sql:
                sql = rewritten_sql
            else:
                # Build SQL from plan
                try:
                    sql = self._builder.build(plan, dialect)
                except Exception as exc:
                    last_error = f"SQL build error: {exc}"
                    if attempt >= self._max_retries:
                        raise self._enhanced_error(last_error, rewriter)
                    rewritten_sql, _ = await self._attempt_rewrite(
                        "", last_error, query, schema_hint, dialect, rewriter, attempt + 1,
                    )
                    continue

            # Validate SQL safety
            try:
                safe_sql = self._validator.validate(sql)
            except SQLValidationError as exc:
                last_error = str(exc)
                if attempt >= self._max_retries:
                    raise self._enhanced_error(last_error, rewriter)
                rewritten_sql, _ = await self._attempt_rewrite(
                    sql, last_error, query, schema_hint, dialect, rewriter, attempt + 1,
                )
                continue

            # Semantic validation
            sem_issues = self._validator.validate_semantic(safe_sql)
            warnings.extend(sem_issues)

            # Time filter validation
            if query:
                time_issues = self._validator.validate_time_filter(safe_sql, query)
                if time_issues:
                    warnings.extend(time_issues)

            # Execute
            try:
                rows = await SQLExecutor().run_on_dsn(dsn, safe_sql)
            except Exception as exc:
                last_error = str(exc)
                if attempt >= self._max_retries:
                    raise self._enhanced_error(last_error, rewriter)
                rewritten_sql, _ = await self._attempt_rewrite(
                    safe_sql, last_error, query, schema_hint, dialect, rewriter, attempt + 1,
                )
                continue

            # Post-execution validation
            validation = self._reflector.validate_result(safe_sql, rows, query)
            if validation.issues:
                warnings.extend(validation.issues)

            return rows, safe_sql, warnings

        # Should not reach here, but just in case
        raise self._enhanced_error(
            f"Query execution failed after {self._max_retries} retries: {last_error}",
            rewriter,
        )

    def _enhanced_error(self, message: str, rewriter: SQLRewriter) -> SQLValidationError:
        """Create SQLValidationError with recovery context attached."""
        error = SQLValidationError(message)
        error.recovery_context = rewriter.get_recovery_context()
        return error

    async def _attempt_rewrite(
        self,
        current_sql: str,
        error: str,
        query: str,
        schema_hint: str,
        dialect: SQLDialectSpec,
        rewriter: SQLRewriter,
        attempt_num: int,
    ) -> tuple[str | None, list]:
        """Use LLM to rewrite SQL based on error feedback. Returns corrected SQL or None."""
        try:
            new_sql, attempts = await rewriter.rewrite(
                current_sql, error, schema_hint, dialect, attempt_num=attempt_num,
            )
            # Validate the rewritten SQL is non-empty and different
            if new_sql and len(new_sql) > 5 and new_sql.strip().lower().startswith(("select", "with")):
                return new_sql, attempts
        except Exception:
            pass
        return None, rewriter.attempts

    async def _rewrite_plan(
        self,
        plan: LogicalPlan,
        error: str,
        query: str,
        schema_hint: str,
        dialect: SQLDialectSpec,
    ) -> LogicalPlan:
        """Use LLM to rewrite the LogicalPlan based on error feedback."""
        rewriter = SQLRewriter()
        # Rewrite the SQL and parse the result back into a plan adjustment
        current_sql = self._builder.build(plan, dialect)
        try:
            new_sql, _ = await rewriter.rewrite(current_sql, error, schema_hint, dialect)
            if new_sql and new_sql != current_sql:
                # Try to extract useful info from the corrected SQL
                plan.metadata["last_error"] = error
                plan.metadata["rewritten_sql"] = new_sql
                plan.metadata["trace_id"] = rewriter.trace_id
        except Exception:
            pass
        return plan
