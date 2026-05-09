from __future__ import annotations

import os
import time
from typing import Any

from execution.data.db_router import DBConnectionInfo, DBRouter
from gateway.api_gateway.routers.databases import _dec
from infra.config.settings import settings
from infra.metadata.schema_inspector import build_schema_hint, load_schema_inspection
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import DataSource, DataSourceSchema
from sqlalchemy import select

from agents.base import AgentResult, BaseAgent, TaskMessage
from kernel.data_cognition.explanation import build_explanation, format_explanation
from kernel.data_cognition.query_executor import QueryExecutor
from kernel.data_cognition.query_planner import QueryPlanner
from kernel.data_cognition.semantic_parser import SemanticParser
from kernel.data_cognition.sql_builder import SQLBuilder
from kernel.data_cognition.sql_dialect import SQLDialectSpec, detect_sql_dialect
from kernel.data_cognition.sql_ranker import SQLRanker
from kernel.data_cognition.sql_reflector import SQLReflector
from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator
from kernel.data_cognition.types import CandidateSQL, SemanticContext


class DataAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("data")
        self.validator = SQLValidator(default_limit=100)
        self.ranker = SQLRanker()
        self.reflector = SQLReflector()
        # Pipeline mode components (lazy-initialized)
        self._semantic_parser: SemanticParser | None = None
        self._query_planner: QueryPlanner | None = None
        self._sql_builder: SQLBuilder | None = None
        self._query_executor: QueryExecutor | None = None
        # Mode: "pipeline" (default) or "llm_direct"
        self._mode = os.getenv("NL2SQL_MODE", "pipeline").lower()

    async def execute(self, task: TaskMessage) -> AgentResult:
        start_ts = time.monotonic()
        try:
            data_source_id = str(task.params.get("data_source_id", "")).strip()
            sql = str(task.params.get("sql", "")).strip() or task.query.strip()
            if not data_source_id:
                return AgentResult(
                    task_id=task.task_id, agent_type=self.agent_type, status="error", content="",
                    error="data_source_id is required",
                )

            async with AsyncSessionLocal() as db:
                r = await db.execute(select(DataSource).where(DataSource.id == data_source_id))
                ds = r.scalar_one_or_none()
                inspection = await load_schema_inspection(db, data_source_id)
                schema_r = await db.execute(
                    select(DataSourceSchema).where(DataSourceSchema.data_source_id == data_source_id)
                )
                schema_row = schema_r.scalar_one_or_none()
                semantic_config = schema_row.semantic_mappings if schema_row else {}

            if ds is None:
                return AgentResult(
                    task_id=task.task_id, agent_type=self.agent_type, status="error", content="",
                    error="data source not found",
                )

            dialect = detect_sql_dialect(ds.source_type)
            schema_hint = build_schema_hint(inspection.schema_payload)
            table_names = inspection.table_names
            table_columns = inspection.column_map if hasattr(inspection, "column_map") else {}

            # Pipeline mode
            if self._mode == "pipeline":
                return await self._execute_pipeline(
                    task, ds, dialect, data_source_id, schema_hint,
                    table_names, table_columns, semantic_config,
                )

            # LLM direct mode (legacy fallback)
            return await self._execute_llm_direct(
                task, ds, dialect, data_source_id, sql, schema_hint,
                semantic_config, start_ts,
            )

        except SQLValidationError as exc:
            return AgentResult(
                task_id=task.task_id, agent_type=self.agent_type, status="error", content="",
                error=f"invalid sql: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            if "access denied" in error_msg.lower() or "authentication failed" in error_msg.lower():
                error_msg = f"数据库连接失败：{error_msg}。请检查用户名和密码。"
            elif "connection refused" in error_msg.lower() or "could not connect" in error_msg.lower():
                error_msg = f"数据库连接失败：{error_msg}。请检查主机和端口，确保数据库服务正在运行。"
            elif "does not exist" in error_msg.lower() or "unknown database" in error_msg.lower():
                error_msg = f"数据库不存在：{error_msg}。请检查数据库名称。"
            elif "table" in error_msg.lower() and "not exist" in error_msg.lower():
                error_msg = f"表不存在：{error_msg}。请检查表名或同步数据库模式。"
            return AgentResult(
                task_id=task.task_id, agent_type=self.agent_type, status="error", content="",
                error=error_msg,
            )

    async def _execute_pipeline(
        self,
        task: TaskMessage,
        ds: DataSource,
        dialect: SQLDialectSpec,
        data_source_id: str,
        schema_hint: str,
        table_names: list[str],
        table_columns: dict[str, list[str]],
        semantic_config: dict[str, Any],
    ) -> AgentResult:
        """Execute using the new multi-stage pipeline: parse → plan → build → execute."""
        start_ts = time.monotonic()
        dsn = self._build_dsn(ds)

        # Lazy init pipeline components
        if self._semantic_parser is None:
            self._semantic_parser = SemanticParser(
                schema_summary=schema_hint,
                table_names=table_names,
                semantic_config=semantic_config,
                table_columns=table_columns,
            )
            self._query_planner = QueryPlanner(
                table_names=table_names, schema_summary=schema_hint,
            )
            self._sql_builder = SQLBuilder(default_limit=100)
            self._query_executor = QueryExecutor(
                validator=self.validator,
                builder=self._sql_builder,
                reflector=self.reflector,
                max_retries=2,
            )

        # Step 1: Check structured intent (table_count, table_list, table_schema)
        structured_sql = self._semantic_parser.check_structured_intent(
            task.query, table_names, ds.database, dialect,
        )
        if structured_sql:
            safe_sql = self.validator.validate(structured_sql)
            return await self._execute_and_return(
                task, safe_sql, ds, dialect, data_source_id,
                meta={"mode": "pipeline_structured"},
            )

        # Step 2: Semantic parsing
        try:
            semantics = await self._semantic_parser.parse(task.query, dialect)
        except Exception as exc:
            # Fall back to llm_direct on parse failure
            return await self._execute_llm_direct(
                task, ds, dialect, data_source_id, task.query, schema_hint,
                semantic_config, start_ts,
                fallback_reason=f"semantic_parse_failed: {exc}",
            )

        # Step 3: Query planning → LogicalPlan
        try:
            plan = await self._query_planner.plan(
                semantics=semantics,
                query=task.query,
                table_names=table_names,
                schema_summary=schema_hint,
                dialect=dialect,
                table_columns=table_columns,
            )
        except Exception as exc:
            return await self._execute_llm_direct(
                task, ds, dialect, data_source_id, task.query, schema_hint,
                semantic_config, start_ts,
                fallback_reason=f"query_plan_failed: {exc}",
            )

        # Step 4: Execute with self-validation + auto-retry
        try:
            rows, final_sql, warnings = await self._query_executor.run_with_retry(
                plan=plan,
                dsn=dsn,
                dialect=dialect,
                query=task.query,
                schema_hint=schema_hint,
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id, agent_type=self.agent_type, status="error", content="",
                error=f"query execution failed: {exc}",
            )

        elapsed_ms = (time.monotonic() - start_ts) * 1000
        confidence = self._compute_confidence(rows, None, mode="pipeline")

        # Step 5: Build explanation
        explanation = build_explanation(plan, final_sql, rows, task.query, warnings)

        row_count = len(rows)
        from kernel.result_reference import ResultRef, serialize_refs

        result_refs = serialize_refs([
            ResultRef(
                ref_id=f"sql:{task.task_id}",
                type="sql",
                title=f"SQL: {task.query[:60]}",
                summary=f"Generated SQL ({len(final_sql)} chars, {row_count} rows)",
                payload={"sql": final_sql, "dialect": str(dialect), "row_count": row_count},
                source_agent="data",
                message_id=task.task_id,
            ),
            ResultRef(
                ref_id=f"table:{task.task_id}",
                type="table",
                title=f"Results: {task.query[:60]}",
                summary=f"{row_count} rows returned",
                payload={"rows_preview": rows[:5], "row_count": row_count},
                source_agent="data",
                message_id=task.task_id,
            ),
        ])
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"data rows={row_count}",
            confidence=confidence,
            metadata={
                "sql": final_sql,
                "rows": rows[:20],
                "row_count": row_count,
                "data_source_id": data_source_id,
                "mode": "pipeline",
                "plan_json": plan.to_json(),
                "explanation": format_explanation(explanation, include_sql=False),
                "tables_used": explanation.tables_used,
                "elapsed_ms": round(elapsed_ms, 1),
                "result_refs": result_refs,
            },
            agent_trace={
                "agent_type": self.agent_type,
                "task_id": task.task_id,
                "problem_identification": task.query,
                "metric_mapping": getattr(plan, "metric_mappings", {}),
                "filters": getattr(plan, "filters", []),
                "join_paths": getattr(plan, "join_paths", []),
                "sql_generated": final_sql,
                "sql_rewrites": [],
                "validation_errors": warnings,
                "execution_result": {"row_count": len(rows), "sample": rows[:5]},
                "confidence": confidence,
            },
            evidence=[
                self._make_evidence(
                    source=f"sql:{data_source_id}",
                    source_type="sql",
                    payload={"sql": final_sql, "row_count": len(rows), "tables": explanation.tables_used},
                    credibility=confidence,
                    relevance=0.9,
                    cost=round(elapsed_ms, 1),
                )
            ],
        )

    async def _execute_llm_direct(
        self,
        task: TaskMessage,
        ds: DataSource,
        dialect: SQLDialectSpec,
        data_source_id: str,
        sql: str,
        schema_hint: str,
        semantic_config: dict[str, Any],
        start_ts: float,
        fallback_reason: str = "",
    ) -> AgentResult:
        """Legacy LLM direct SQL generation mode."""
        from kernel.data_cognition.sql_postprocess import normalize_sql_for_dialect
        from kernel.data_cognition.sql_planner import SQLPlanner
        from kernel.data_cognition.semantic_layer import SemanticLayer

        planner = SQLPlanner()
        semantic_layer = SemanticLayer(semantic_config)
        semantic_ctx = semantic_layer.resolve(task.query, dialect)

        # Supplement with heuristic time intent
        if not semantic_ctx.time_macros:
            time_intent = semantic_layer.extract_time_intent(task.query)
            if time_intent:
                semantic_ctx.time_macros.append(time_intent)

        # SQL generation
        if not sql.lower().startswith(("select", "with", "show", "describe")):
            planned = await planner.plan(task.query, schema_hint=schema_hint, dialect=dialect)
            sql = planned.sql

        # Re-plan with schema guidance if needed
        if not sql.lower().startswith(("select", "with")) and schema_hint and len(schema_hint) > 40:
            planned = await planner.plan(task.query, schema_hint=schema_hint, dialect=dialect)
            sql = planned.sql

        # Multi-candidate generation
        semantic_fragments = semantic_ctx.resolved_sql_fragments if semantic_ctx.resolved_sql_fragments else None
        candidates = await planner.generate_candidates(
            task.query, schema_hint=schema_hint, dialect=dialect, n=4,
            semantic_fragments=semantic_fragments,
        )

        if sql and not any(c.sql.lower() == sql.lower() for c in candidates):
            candidates.insert(0, CandidateSQL(sql=sql, source_template="initial"))

        ranked = self.ranker.rank(candidates, semantic_ctx, schema_hint)
        best_sql = self._select_valid_sql(ranked, semantic_ctx, task.query)
        if not best_sql:
            return AgentResult(
                task_id=task.task_id, agent_type=self.agent_type, status="error", content="",
                error="no valid SQL candidate found after ranking and validation",
            )

        safe_sql = self.validator.validate(normalize_sql_for_dialect(best_sql, dialect))
        rows, final_sql = await self._execute_with_reflection(
            safe_sql, ds, dialect, task.query, schema_hint, semantic_ctx,
        )

        elapsed_ms = (time.monotonic() - start_ts) * 1000
        confidence = self._compute_confidence(rows, semantic_ctx, mode="llm_direct")

        from kernel.result_reference import ResultRef, serialize_refs

        result_refs = serialize_refs([
            ResultRef(
                ref_id=f"sql:{task.task_id}",
                type="sql",
                title=f"SQL: {task.query[:60]}",
                summary=f"Generated SQL ({len(final_sql)} chars, {len(rows)} rows)",
                payload={"sql": final_sql, "dialect": str(dialect), "row_count": len(rows)},
                source_agent="data",
                message_id=task.task_id,
            ),
            ResultRef(
                ref_id=f"table:{task.task_id}",
                type="table",
                title=f"Results: {task.query[:60]}",
                summary=f"{len(rows)} rows returned",
                payload={"rows_preview": rows[:5], "row_count": len(rows)},
                source_agent="data",
                message_id=task.task_id,
            ),
        ])
        meta: dict[str, Any] = {
            "sql": final_sql,
            "rows": rows[:20],
            "row_count": len(rows),
            "data_source_id": data_source_id,
            "mode": "llm_direct",
            "ranked_candidates": len(candidates),
            "semantic_mappings": len(semantic_ctx.dimension_mappings),
            "elapsed_ms": round(elapsed_ms, 1),
            "result_refs": result_refs,
        }
        if fallback_reason:
            meta["fallback_reason"] = fallback_reason

        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"data rows={len(rows)}",
            confidence=confidence,
            metadata=meta,
            agent_trace={
                "agent_type": self.agent_type,
                "task_id": task.task_id,
                "problem_identification": task.query,
                "sql_generated": safe_sql,
                "execution_result": {"row_count": len(rows), "sample": rows[:5]},
                "confidence": confidence,
                "mode": "llm_direct",
            },
            evidence=[
                self._make_evidence(
                    source=f"sql:{data_source_id}",
                    source_type="sql",
                    payload={"sql": safe_sql, "row_count": len(rows)},
                    credibility=confidence,
                    relevance=0.85,
                    cost=round(elapsed_ms, 1),
                )
            ],
        )

    def _select_valid_sql(self, ranked: list[CandidateSQL], semantic_ctx: SemanticContext | None, query: str) -> str | None:
        """Select the best valid SQL from ranked candidates."""
        for c in ranked:
            time_issues = self.validator.validate_time_filter(c.sql, query)
            if time_issues:
                continue
            return c.sql
        # All candidates failed time filter — return the highest-ranked one with a warning
        return ranked[0].sql if ranked else None

    async def _execute_with_reflection(
        self, safe_sql: str, ds: DataSource, dialect: SQLDialectSpec, query: str, schema_hint: str, semantic_ctx: SemanticContext | None,
    ) -> tuple[list, str]:
        dsn = self._build_dsn(ds)
        max_rounds = self.reflector.MAX_REFLECTION_ROUNDS
        current_sql = safe_sql
        from kernel.data_cognition.sql_rewriter import SQLRewriter
        rewriter = SQLRewriter()

        for attempt in range(max_rounds + 1):
            try:
                rows = await SQLExecutor_from_executor().run_on_dsn(dsn, current_sql)
                validation = self.reflector.validate_result(current_sql, rows, query, semantic_ctx)
                if validation.passed or attempt >= max_rounds:
                    return rows, current_sql
                fixed_sql = await rewriter.rewrite(current_sql, "; ".join(validation.issues), schema_hint, dialect)
                if not fixed_sql:
                    break
                try:
                    current_sql = self.validator.validate(fixed_sql)
                except Exception:
                    break
            except Exception as exc:
                if attempt >= max_rounds:
                    raise
                fixed_sql = await rewriter.rewrite(current_sql, str(exc), schema_hint, dialect)
                if not fixed_sql:
                    break
                try:
                    current_sql = self.validator.validate(fixed_sql)
                except Exception:
                    break

        return [], current_sql

    def _compute_confidence(self, rows: list, semantic_ctx: SemanticContext | None, mode: str = "pipeline") -> float:
        """Compute confidence score based on actual result characteristics."""
        confidence = 0.60  # base

        # Pipeline mode is inherently more trustworthy (structured reasoning)
        if mode == "pipeline":
            confidence += 0.15

        # Has result rows
        if rows:
            confidence += 0.10
            if len(rows) >= 3:
                confidence += 0.05  # multiple rows = more likely correct

        # Semantic resolution quality
        if semantic_ctx:
            if semantic_ctx.dimension_mappings:
                confidence += 0.05
            if semantic_ctx.metric_defs:
                confidence += 0.05
            if semantic_ctx.time_macros:
                confidence += 0.03

        return min(confidence, 0.99)

    def _build_dsn(self, ds: DataSource) -> str:
        return DBRouter().build_dsn(
            DBConnectionInfo(
                source_type=ds.source_type,
                host=ds.host,
                port=ds.port,
                database=ds.database,
                username=ds.username,
                password=_dec(ds.password_encrypted),
            )
        )

    async def _execute_and_return(
        self, task: TaskMessage, safe_sql: str, ds: DataSource, dialect: SQLDialectSpec, data_source_id: str, meta: dict,
    ) -> AgentResult:
        dsn = self._build_dsn(ds)
        rows = await SQLExecutor_from_executor().run_on_dsn(dsn, safe_sql)
        row_count = len(rows)
        from kernel.result_reference import ResultRef, serialize_refs

        result_refs = serialize_refs([
            ResultRef(
                ref_id=f"sql:{task.task_id}",
                type="sql",
                title=f"SQL: {task.query[:60]}",
                summary=f"Generated SQL ({len(safe_sql)} chars, {row_count} rows)",
                payload={"sql": safe_sql, "dialect": str(dialect), "row_count": row_count},
                source_agent="data",
                message_id=task.task_id,
            ),
            ResultRef(
                ref_id=f"table:{task.task_id}",
                type="table",
                title=f"Results: {task.query[:60]}",
                summary=f"{row_count} rows returned",
                payload={"rows_preview": rows[:5], "row_count": row_count},
                source_agent="data",
                message_id=task.task_id,
            ),
        ])
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"data rows={row_count}",
            confidence=0.95,
            metadata={"sql": safe_sql, "rows": rows[:20], "row_count": row_count, "data_source_id": data_source_id, "result_refs": result_refs, **meta},
            evidence=[
                self._make_evidence(
                    source=f"sql:{data_source_id}",
                    source_type="sql",
                    payload={"sql": safe_sql, "row_count": len(rows)},
                    credibility=0.95,
                    relevance=0.9,
                )
            ],
        )


def SQLExecutor_from_executor():
    from execution.data.sql_executor import SQLExecutor
    return SQLExecutor()
