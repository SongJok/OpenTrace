from __future__ import annotations

import os
import time
from typing import Any

from sqlalchemy import select

from agents.base import AgentResult, BaseAgent, TaskMessage
from execution.data.database_hosts import format_database_connection_error
from execution.data.db_router import DBConnectionInfo, DBRouter
from infra.metadata.schema_inspector import build_schema_hint, load_schema_inspection
from infra.security.data_source_secrets import decrypt_data_source_secret
from infra.security.resource_scope import get_accessible_data_source
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import DataSource, DataSourceSchema
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

# ── 在线 DataAgent 统一入口 ─────────────────────────────────────────────


class DataAgent(BaseAgent):
    """DataAgent 在线入口：只生成治理运行和待确认 SQL 草案。"""

    def __init__(self) -> None:
        super().__init__("data")

    async def execute(self, task: TaskMessage) -> AgentResult:
        try:
            return await self._generate_sql_draft(task)
        except Exception as exc:  # noqa: BLE001 - 统一转为 AgentResult 错误契约
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error=f"DataAgent SQL 草案生成失败：{exc}",
            )

    async def _generate_sql_draft(self, task: TaskMessage) -> AgentResult:
        """交互式问数生成持久化治理运行及确认执行投影。"""

        from infra.security.resource_scope import get_accessible_data_source
        from infra.storage.database import AsyncSessionLocal
        from services.sql_assets import generate_sql_query_draft, serialize_draft

        data_source_id = str(task.params.get("data_source_id") or "").strip()
        tenant_id = str(task.params.get("tenant_id") or "").strip()
        workspace_id = str(task.params.get("workspace_id") or "").strip()
        user_id = str(task.user_id or "").strip()
        if not all((data_source_id, tenant_id, workspace_id, user_id)):
            raise ValueError("trusted data source scope is required")
        async with AsyncSessionLocal() as db:
            source = await get_accessible_data_source(
                db,
                user_id=user_id,
                tenant_metadata={"tenant_id": tenant_id, "workspace_id": workspace_id},
                data_source_id=data_source_id,
                required_permission="query",
                active_only=True,
            )
            if source is None:
                raise PermissionError("data source not found or not authorized")
            draft, candidates = await generate_sql_query_draft(
                db,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                data_source=source,
                question=task.query,
                supplied_sql=str(task.params.get("sql") or "") or None,
                conversation_id=str(task.params.get("conversation_id") or task.session_id or "")
                or None,
                response_id=str(task.params.get("response_id") or "") or None,
                group_type=str(task.params.get("group_type") or "alternative"),
                output_mode=str(task.params.get("output_mode") or "sql_only"),
                clarification_context=str(task.params.get("clarify_context") or "") or None,
                source_decision=(
                    task.params.get("source_decision")
                    if isinstance(task.params.get("source_decision"), dict)
                    else None
                ),
            )
            payload = serialize_draft(draft, candidates)
            source_decision = task.params.get("source_decision")
            if isinstance(source_decision, dict):
                payload["source_decision"] = source_decision
            company_skill_evidence = [
                dict(item)
                for item in task.params.get("company_skill_evidence") or []
                if isinstance(item, dict)
            ][:3]
            if company_skill_evidence:
                payload["company_skill_evidence"] = company_skill_evidence
        if draft.status == "needs_clarification":
            question_text = str(payload["clarification"].get("question_text") or "请补充查询口径。")
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=question_text,
                confidence=0.9,
                metadata={
                    "mode": "clarification",
                    "needs_clarification": True,
                    "clarification": payload["clarification"],
                    "draft_id": draft.id,
                    "draft": payload,
                    "source_decision": payload.get("source_decision", {}),
                    "company_skill_evidence": payload.get("company_skill_evidence", []),
                    "executed": False,
                },
            )
        rendered = [
            "SQL 草案已生成，尚未执行。",
            f"草案 ID：{draft.id}",
        ]
        for candidate in candidates:
            rendered.extend(
                [
                    f"\n候选 {candidate.position}（ID：{candidate.id}）",
                    f"```sql\n{candidate.sql}\n```",
                ]
            )
        rendered.append("\n请用户选择具体候选，或明确要求执行全部候选。")
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content="\n".join(rendered),
            confidence=0.9,
            metadata={
                "mode": "sql_draft_generation",
                "sql": candidates[0].sql if candidates else "",
                "rows": [],
                "executed": False,
                "draft_id": draft.id,
                "candidates": payload["candidates"],
                "draft": payload,
                "source_decision": payload.get("source_decision", {}),
                "company_skill_evidence": payload.get("company_skill_evidence", []),
                "query_plan": payload["query_plan"],
            },
        )


# ── 离线兼容流水线（不在在线 DataAgent 主路径）────────────────────────


class DataAgentV1(BaseAgent):
    def __init__(self) -> None:
        super().__init__("data")
        self.validator = SQLValidator(default_limit=100)
        self.ranker = SQLRanker()
        self.reflector = SQLReflector()
        # 流水线模式组件（惰性初始化）
        self._semantic_parser: SemanticParser | None = None
        self._query_planner: QueryPlanner | None = None
        self._sql_builder: SQLBuilder | None = None
        self._query_executor: QueryExecutor | None = None
        # 模式："pipeline"（默认）或 "llm_direct"
        self._mode = os.getenv("DATA_AGENT_MODE", "pipeline").lower()

    async def execute(self, task: TaskMessage) -> AgentResult:
        start_ts = time.monotonic()
        try:
            data_source_id = str(task.params.get("data_source_id", "")).strip()
            sql = str(task.params.get("sql", "")).strip() or task.query.strip()
            if not data_source_id:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error="data_source_id is required",
                )

            user_id = str(task.user_id or "").strip()
            tenant_id = str(task.params.get("tenant_id") or "").strip()
            workspace_id = str(task.params.get("workspace_id") or "").strip()
            if not user_id or not tenant_id or not workspace_id:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error="trusted data source scope is required",
                )

            async with AsyncSessionLocal() as db:
                ds = await get_accessible_data_source(
                    db,
                    user_id=user_id,
                    tenant_metadata={"tenant_id": tenant_id, "workspace_id": workspace_id},
                    data_source_id=data_source_id,
                    required_permission="query",
                    active_only=True,
                )
                if ds is not None:
                    inspection = await load_schema_inspection(db, data_source_id)
                    schema_r = await db.execute(
                        select(DataSourceSchema).where(
                            DataSourceSchema.data_source_id == data_source_id
                        )
                    )
                    schema_row = schema_r.scalar_one_or_none()
                    semantic_config = schema_row.semantic_mappings if schema_row else {}
                else:
                    inspection = None
                    semantic_config = {}

            if ds is None:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error="data source not found or not authorized",
                )

            dialect = detect_sql_dialect(ds.source_type)
            assert inspection is not None
            schema_hint = build_schema_hint(inspection.schema_payload)
            table_names = inspection.table_names
            table_columns = inspection.column_map if hasattr(inspection, "column_map") else {}

            # 流水线模式
            if self._mode == "pipeline":
                return await self._execute_pipeline(
                    task,
                    ds,
                    dialect,
                    data_source_id,
                    schema_hint,
                    table_names,
                    table_columns,
                    semantic_config,
                )

            # LLM 直连模式（遗留回退）
            return await self._execute_llm_direct(
                task,
                ds,
                dialect,
                data_source_id,
                sql,
                schema_hint,
                semantic_config,
                start_ts,
                table_columns,
            )

        except SQLValidationError as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error=f"invalid sql: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            host = port = database = None
            try:
                if ds is not None:
                    host, port, database = ds.host, ds.port, ds.database
            except NameError:
                pass
            error_msg = format_database_connection_error(
                exc,
                configured_host=host or "",
                port=port,
                database=database,
            )
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
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
        """多阶段流水线执行：解析 → 规划 → 构建 → 执行。"""
        start_ts = time.monotonic()
        dsn = self._build_dsn(ds)

        # 惰性初始化流水线组件
        if self._semantic_parser is None:
            self._semantic_parser = SemanticParser(
                schema_summary=schema_hint,
                table_names=table_names,
                semantic_config=semantic_config,
                table_columns=table_columns,
            )
            self._query_planner = QueryPlanner(
                table_names=table_names,
                schema_summary=schema_hint,
            )
            self._sql_builder = SQLBuilder(default_limit=100)
            self._query_executor = QueryExecutor(
                validator=self.validator,
                builder=self._sql_builder,
                reflector=self.reflector,
                max_retries=2,
            )
        assert self._query_planner is not None
        assert self._query_executor is not None

        # 步骤 1：检查结构化意图（table_count、table_list、table_schema）
        structured_sql = self._semantic_parser.check_structured_intent(
            task.query,
            table_names,
            ds.database,
            dialect,
        )
        if structured_sql:
            safe_sql = self.validator.validate(structured_sql)
            return await self._execute_and_return(
                task,
                safe_sql,
                ds,
                dialect,
                data_source_id,
                meta={"mode": "pipeline_structured"},
                table_columns=table_columns,
            )

        # 步骤 2：语义解析
        try:
            semantics = await self._semantic_parser.parse(task.query, dialect)
        except Exception as exc:
            # 解析失败时回退 llm_direct
            return await self._execute_llm_direct(
                task,
                ds,
                dialect,
                data_source_id,
                task.query,
                schema_hint,
                semantic_config,
                start_ts,
                table_columns,
                fallback_reason=f"semantic_parse_failed: {exc}",
            )

        # 步骤 3：查询规划 → LogicalPlan
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
                task,
                ds,
                dialect,
                data_source_id,
                task.query,
                schema_hint,
                semantic_config,
                start_ts,
                table_columns,
                fallback_reason=f"query_plan_failed: {exc}",
            )

        # 步骤 4：自校验 + 自动重试执行
        try:
            rows, final_sql, warnings = await self._query_executor.run_with_retry(
                plan=plan,
                dsn=dsn,
                dialect=dialect,
                query=task.query,
                schema_hint=schema_hint,
                table_columns=table_columns,
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error=f"query execution failed: {exc}",
            )

        elapsed_ms = (time.monotonic() - start_ts) * 1000
        confidence = self._compute_confidence(rows, None, mode="pipeline")

        # 步骤 5：生成解释
        explanation = build_explanation(plan, final_sql, rows, task.query, warnings)

        row_count = len(rows)
        from kernel.result_reference import ResultRef, serialize_refs

        result_refs = serialize_refs(
            [
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
            ]
        )
        meta = {
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
        }
        try:
            from services.data_intelligence_runtime import attach_data_intelligence_to_metadata

            meta = attach_data_intelligence_to_metadata(
                meta,
                query=task.query,
                sql=final_sql,
                row_count=row_count,
                metric_names=list(getattr(plan, "metric_mappings", {}) or {}),
            )
        except Exception:
            pass
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"data rows={row_count}",
            confidence=confidence,
            metadata=meta,
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
                    payload={
                        "sql": final_sql,
                        "row_count": len(rows),
                        "tables": explanation.tables_used,
                    },
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
        table_columns: dict[str, list[str]],
        fallback_reason: str = "",
    ) -> AgentResult:
        """遗留 LLM 直连 SQL 生成模式。"""
        from kernel.data_cognition.semantic_layer import SemanticLayer
        from kernel.data_cognition.sql_planner import SQLPlanner
        from kernel.data_cognition.sql_postprocess import normalize_sql_for_dialect

        planner = SQLPlanner()
        semantic_layer = SemanticLayer(semantic_config)
        semantic_ctx = semantic_layer.resolve(task.query, dialect)

        # 启发式时间意图补充
        if not semantic_ctx.time_macros:
            time_intent = semantic_layer.extract_time_intent(task.query)
            if time_intent:
                semantic_ctx.time_macros.append(time_intent)

        # SQL 生成
        if not sql.lower().startswith(("select", "with", "show", "describe")):
            planned = await planner.plan(task.query, schema_hint=schema_hint, dialect=dialect)
            sql = planned.sql

        # 必要时按 schema 指引重新规划
        if not sql.lower().startswith(("select", "with")) and schema_hint and len(schema_hint) > 40:
            planned = await planner.plan(task.query, schema_hint=schema_hint, dialect=dialect)
            sql = planned.sql

        # 多候选 SQL 生成
        semantic_fragments = (
            semantic_ctx.resolved_sql_fragments if semantic_ctx.resolved_sql_fragments else None
        )
        candidates = await planner.generate_candidates(
            task.query,
            schema_hint=schema_hint,
            dialect=dialect,
            n=4,
            semantic_fragments=semantic_fragments,
        )

        if sql and not any(c.sql.lower() == sql.lower() for c in candidates):
            candidates.insert(0, CandidateSQL(sql=sql, source_template="initial"))

        ranked = self.ranker.rank(candidates, semantic_ctx, schema_hint)
        best_sql = self._select_valid_sql(ranked, semantic_ctx, task.query)
        if not best_sql:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error="no valid SQL candidate found after ranking and validation",
            )

        safe_sql = self.validator.validate(normalize_sql_for_dialect(best_sql, dialect))
        rows, final_sql = await self._execute_with_reflection(
            safe_sql,
            ds,
            dialect,
            task.query,
            schema_hint,
            semantic_ctx,
            table_columns,
        )

        elapsed_ms = (time.monotonic() - start_ts) * 1000
        confidence = self._compute_confidence(rows, semantic_ctx, mode="llm_direct")

        from kernel.result_reference import ResultRef, serialize_refs

        result_refs = serialize_refs(
            [
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
            ]
        )
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

    def _select_valid_sql(
        self, ranked: list[CandidateSQL], semantic_ctx: SemanticContext | None, query: str
    ) -> str | None:
        """从排序后的候选中选取最优合法 SQL。"""
        for c in ranked:
            time_issues = self.validator.validate_time_filter(c.sql, query)
            if time_issues:
                continue
            return c.sql
        # 时间过滤均未通过 — 仍返回排名第一的候选并告警
        return ranked[0].sql if ranked else None

    async def _execute_with_reflection(
        self,
        safe_sql: str,
        ds: DataSource,
        dialect: SQLDialectSpec,
        query: str,
        schema_hint: str,
        semantic_ctx: SemanticContext | None,
        table_columns: dict[str, list[str]],
    ) -> tuple[list, str]:
        dsn = self._build_dsn(ds)
        max_rounds = self.reflector.MAX_REFLECTION_ROUNDS
        current_sql = safe_sql
        from kernel.data_cognition.sql_rewriter import SQLRewriter

        rewriter = SQLRewriter()

        for attempt in range(max_rounds + 1):
            try:
                rows = await SQLExecutor_from_executor().run_on_dsn(  # noqa: N802
                    dsn,
                    current_sql,
                    source_type=ds.source_type,
                    table_columns=table_columns,
                )
                validation = self.reflector.validate_result(current_sql, rows, query, semantic_ctx)
                if validation.passed or attempt >= max_rounds:
                    return rows, current_sql
                fixed_sql = await rewriter.rewrite(
                    current_sql, "; ".join(validation.issues), schema_hint, dialect
                )
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

    def _compute_confidence(
        self, rows: list, semantic_ctx: SemanticContext | None, mode: str = "pipeline"
    ) -> float:
        """根据实际结果特征计算置信度。"""
        confidence = 0.60  # 基线

        # 流水线模式更可信（结构化推理）
        if mode == "pipeline":
            confidence += 0.15

        # 有结果行
        if rows:
            confidence += 0.10
            if len(rows) >= 3:
                confidence += 0.05  # 多行更可能正确

        # 语义解析质量
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
                password=decrypt_data_source_secret(ds.password_encrypted),
            )
        )

    async def _execute_and_return(
        self,
        task: TaskMessage,
        safe_sql: str,
        ds: DataSource,
        dialect: SQLDialectSpec,
        data_source_id: str,
        meta: dict,
        table_columns: dict[str, list[str]],
    ) -> AgentResult:
        dsn = self._build_dsn(ds)
        rows = await SQLExecutor_from_executor().run_on_dsn(  # noqa: N802
            dsn,
            safe_sql,
            source_type=ds.source_type,
            table_columns=table_columns,
        )
        row_count = len(rows)
        from kernel.result_reference import ResultRef, serialize_refs

        result_refs = serialize_refs(
            [
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
            ]
        )
        sql_summary = f"SQL ({row_count} rows): {safe_sql[:500]}"
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"data rows={row_count}",
            confidence=0.95,
            metadata={
                "sql": safe_sql,
                "rows": rows[:20],
                "row_count": row_count,
                "data_source_id": data_source_id,
                "result_refs": result_refs,
                **meta,
            },
            evidence=[
                self._make_evidence(
                    source=f"sql:{data_source_id}",
                    source_type="sql",
                    payload={"sql": safe_sql, "row_count": len(rows)},
                    credibility=0.95,
                    relevance=0.9,
                )
            ],
            evidence_objects=[
                self._make_evidence_object(
                    content=sql_summary,
                    source_type="sql",
                    credibility=0.95,
                    relevance=0.9,
                    data_source_id=data_source_id,
                    row_count=row_count,
                )
            ],
        )


def SQLExecutor_from_executor():  # noqa: N802
    from execution.data.sql_executor import SQLExecutor

    return SQLExecutor()
