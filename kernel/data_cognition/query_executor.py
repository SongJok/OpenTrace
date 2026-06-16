"""查询执行器 — 执行 SQL，含自校验、自动重试与增强错误恢复。"""

from __future__ import annotations

from typing import Any

from execution.data.sql_executor import SQLExecutor
from kernel.data_cognition.logical_plan import LogicalPlan
from kernel.data_cognition.sql_builder import SQLBuilder
from kernel.data_cognition.sql_dialect import SQLDialectSpec
from kernel.data_cognition.sql_reflector import SQLReflector
from kernel.data_cognition.sql_rewriter import SQLRewriter
from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator


class QueryExecutor:
    """
    执行 SQL，包含验证、结果合理性检查和自动修正。

    流程：
    1. 使用 sqlglot 解析 SQL（语法验证）
    2. 验证只读安全性（SQLValidator）
    3. 执行
    4. 执行后合理性检查（SQLReflector）
    5. 出错时：通过 LLM 重写 LogicalPlan → 重建 SQL → 重试
    6. 最终失败时：返回结构化恢复上下文供用户选择
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
        执行 LogicalPlan，失败时自动重试。

        重试策略：
        - 第 0 次：从计划构建 SQL，验证，执行
        - 第 1 次及以后：LLM 根据错误重写 SQL → 验证重写后的 SQL → 执行

        返回：(rows, final_sql, warnings)
        失败时抛出：带有 recovery_context 属性的 SQLValidationError
        """
        warnings: list[str] = []
        last_error: str = ""
        rewriter = SQLRewriter()
        rewritten_sql: str | None = None

        for attempt in range(self._max_retries + 1):
            # 如果有 LLM 重写的 SQL，直接使用
            if rewritten_sql:
                sql = rewritten_sql
            else:
                # 从计划构建 SQL
                try:
                    sql = self._builder.build(plan, dialect)
                except Exception as exc:
                    last_error = f"SQL build error: {exc}"
                    if attempt >= self._max_retries:
                        raise self._enhanced_error(last_error, rewriter)
                    rewritten_sql, _ = await self._attempt_rewrite(
                        "",
                        last_error,
                        query,
                        schema_hint,
                        dialect,
                        rewriter,
                        attempt + 1,
                    )
                    continue

            # 验证 SQL 安全性
            try:
                safe_sql = self._validator.validate(sql)
            except SQLValidationError as exc:
                last_error = str(exc)
                if attempt >= self._max_retries:
                    raise self._enhanced_error(last_error, rewriter)
                rewritten_sql, _ = await self._attempt_rewrite(
                    sql,
                    last_error,
                    query,
                    schema_hint,
                    dialect,
                    rewriter,
                    attempt + 1,
                )
                continue

            # 语义验证
            sem_issues = self._validator.validate_semantic(safe_sql)
            warnings.extend(sem_issues)

            # 时间过滤器验证
            if query:
                time_issues = self._validator.validate_time_filter(safe_sql, query)
                if time_issues:
                    warnings.extend(time_issues)

            # 执行
            try:
                rows = await SQLExecutor().run_on_dsn(dsn, safe_sql)
            except Exception as exc:
                last_error = str(exc)
                if attempt >= self._max_retries:
                    raise self._enhanced_error(last_error, rewriter)
                rewritten_sql, _ = await self._attempt_rewrite(
                    safe_sql,
                    last_error,
                    query,
                    schema_hint,
                    dialect,
                    rewriter,
                    attempt + 1,
                )
                continue

            # 执行后验证
            validation = self._reflector.validate_result(safe_sql, rows, query)
            if validation.issues:
                warnings.extend(validation.issues)

            return rows, safe_sql, warnings

        # 不应到达此处，但以防万一
        raise self._enhanced_error(
            f"Query execution failed after {self._max_retries} retries: {last_error}",
            rewriter,
        )

    def _enhanced_error(self, message: str, rewriter: SQLRewriter) -> SQLValidationError:
        """创建附带恢复上下文的 SQLValidationError。"""
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
        """使用 LLM 根据错误反馈重写 SQL，返回修正后的 SQL 或 None。"""
        try:
            new_sql = await rewriter.rewrite(
                current_sql,
                error,
                schema_hint,
                dialect,
                attempt_num=attempt_num,
            )
            if (
                new_sql
                and len(new_sql) > 5
                and new_sql.strip().lower().startswith(("select", "with"))
            ):
                return new_sql, rewriter.attempts
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
        """使用 LLM 根据错误反馈重写 LogicalPlan。"""
        rewriter = SQLRewriter()
        current_sql = self._builder.build(plan, dialect)
        try:
            new_sql = await rewriter.rewrite(current_sql, error, schema_hint, dialect)
            if new_sql and new_sql != current_sql:
                plan.metadata["last_error"] = error
                plan.metadata["rewritten_sql"] = new_sql
                plan.metadata["trace_id"] = rewriter.trace_id
        except Exception:
            pass
        return plan
