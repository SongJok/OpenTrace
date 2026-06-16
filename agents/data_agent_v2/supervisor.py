"""
DataAgentV2Supervisor — 编排认知流水线的薄协调器。

职责：
1. 从任务参数初始化认知上下文
2. 运行知识层（KnowledgeRetrieverAgent）
3. 由 CognitiveContext + 特性开关构建 DAG
4. 经内核 DagScheduler 执行 DAG（信号量并行）
5. 校验通过后执行 SQL
6. 反思与自动修复（Phase 2.1）
7. 高级分析（Phase 4）
8. 组装带置信度与轨迹的最终 AgentResult
9. 批评评估（Phase 2.2）
10. 学习流水线（Phase 3）
11. 置信度熔断 — 质量过低时回退 V1

Supervisor 本身不含业务逻辑，仅做协调。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict
from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import CognitiveContext, LowConfidenceError
from infra.observability.logger import get_logger

from agents.data_agent_v2.dag_builder import (
    DagNodeSpec,
    DagPlanSpec,
    build_cognitive_dag,
    get_enabled_agents,
)

logger = get_logger(__name__)


class DataAgentV2Supervisor:
    """DataAgent V2 认知流水线的轻量协调器（tier-2 节点经 tier2_registry）。"""

    def __init__(self) -> None:
        from kernel.agent_runtime.tier2_registry import tier2_registry

        self._tier2 = tier2_registry
        self._max_retries = 2

    async def execute(self, task: TaskMessage) -> AgentResult:
        from infra.config.settings import settings
        self._max_retries = int(getattr(settings, "data_agent_v2_supervisor_max_retries", 2))

        t0 = time.monotonic()
        self._trace_id = str(uuid.uuid4())

        # 1. 初始化认知上下文
        ctx = self._init_context(task)

        # 2. 加载数据源元数据
        await self._load_datasource_metadata(task, ctx)

        # 3. 知识层
        knowledge_enabled = bool(getattr(settings, "data_agent_v2_knowledge_retriever_enabled", True))
        if knowledge_enabled:
            t_kb = time.monotonic()
            ctx = await self._run_knowledge_layer(task, ctx)
            await self._record_event(self._trace_id, task, "knowledge_layer",
                                     {"duration_ms": int((time.monotonic() - t_kb) * 1000)},
                                     status="success")

        # 4. 检查直接 SQL / 模式命中（快速路径：跳过推理 DAG）
        if ctx.compiled_sql:
            ctx.verification_report = ctx.verification_report or {
                "status": "pass",
                "issues": [],
                "source": "direct_sql",
            }
            await self._record_event(self._trace_id, task, "dag_execute",
                                     {"nodes": 0, "direct_sql": True},
                                     status="success")
        elif ctx.pattern_hit and ctx.pattern_hit.get("successful_sql"):
            ctx.compiled_sql = ctx.pattern_hit["successful_sql"]
            await self._record_event(self._trace_id, task, "dag_execute",
                                     {"nodes": 1, "pattern_hit": True},
                                     status="success")
        else:
            # 5. 构建并执行认知 DAG
            enabled_agents = get_enabled_agents()
            is_metadata = (
                ctx.intent and ctx.intent.get("intent_type") == "metadata"
            ) if ctx.intent else False

            dag = build_cognitive_dag(
                query=ctx.query,
                enabled=enabled_agents,
                parallel=bool(getattr(settings, "data_agent_v2_dag_parallel_enabled", True)),
                is_metadata=is_metadata,
            )

            # 5b. 若匹配到技能模板则扩展 DAG（Phase 4.4）
            skill_exec_enabled = enabled_agents.get("skill_execution", False)
            if skill_exec_enabled and ctx.matched_skills:
                dag = self._expand_skills(dag, ctx)

            t_dag = time.monotonic()
            ctx = await self._execute_dag(task, ctx, dag)
            await self._record_event(self._trace_id, task, "dag_execute",
                                     {"nodes": len(dag.nodes), "duration_ms": int((time.monotonic() - t_dag) * 1000)},
                                     status="success")

            ctx = await self._maybe_replan_after_verification_fail(task, ctx, enabled_agents, is_metadata)

        # 5c. 澄清门控：在 SQL 执行前检测模糊查询。
        # 若用户正在回复之前的澄清（clarify_context 非空）则跳过，
        # 此时直接继续执行查询。
        clarification_enabled = bool(getattr(settings, "data_agent_v2_clarification_enabled", True))
        has_clarify_context = bool(ctx.clarify_context)
        if clarification_enabled and not ctx.compiled_sql and not has_clarify_context:
            clarification_question = await self._check_clarification(task, ctx)
            if clarification_question:
                ctx.needs_clarification = True
                ctx.clarification = clarification_question
                await self._record_event(self._trace_id, task, "clarification",
                                         {"reason": "query too vague",
                                          "suggested_options": len(clarification_question.get("suggested_options", []))},
                                         status="success")
                return self._build_clarification_result(task, ctx, t0)

        # 6. 若校验通过则执行 SQL
        t_sql = time.monotonic()
        if bool(task.params.get("dry_run", False)):
            result_ctx = ctx
            result_ctx.execution_rows = []
            result_ctx.execution_row_count = 0
            result_ctx.execution_error = None
        else:
            result_ctx = await self._execute_sql(task, ctx)
        await self._record_event(self._trace_id, task, "sql_execute",
                                 {"row_count": result_ctx.execution_row_count,
                                  "sql_len": len(result_ctx.compiled_sql or ""),
                                  "error": result_ctx.execution_error or "",
                                  "duration_ms": int((time.monotonic() - t_sql) * 1000)},
                                 status="error" if result_ctx.execution_error else "success")

        # 7. 反思：观察结果、诊断、修复（Phase 2.1）
        reflection_enabled = bool(getattr(settings, "data_agent_v2_reflection_enabled", True))
        if reflection_enabled:
            before_reflection_sql = result_ctx.compiled_sql
            result_ctx = await self._run_reflection(task, result_ctx)
            if result_ctx.compiled_sql and result_ctx.compiled_sql != before_reflection_sql:
                result_ctx.execution_error = None
                result_ctx.execution_rows = None
                result_ctx.execution_row_count = 0
                result_ctx = await self._execute_sql(task, result_ctx)
            await self._record_event(self._trace_id, task, "reflection",
                                     {"rounds": result_ctx.reflection_rounds},
                                     status="success")

        # 7b. 高级分析（Phase 4）
        if result_ctx.execution_rows and not result_ctx.execution_error:
            result_ctx = await self._run_advanced_analytics(task, result_ctx)

        # 8. 构建最终结果
        result = self._build_final_result(task, result_ctx, t0)

        # 8b. 置信度熔断：若 V2 结果质量过低，
        # 通知 DataAgent 包装器回退到 V1 流水线。
        threshold = float(getattr(settings, "data_agent_v2_confidence_threshold", 0.40))
        if result.confidence < threshold and bool(getattr(settings, "data_agent_v2_fallback_to_v1", False)):
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            await self._record_event(
                self._trace_id,
                task,
                "circuit_breaker",
                {
                    "confidence": result.confidence,
                    "threshold": threshold,
                    "failure_memory": True,
                },
                status="error",
            )
            try:
                from kernel.agent_runtime.data_v2_failure_memory import record_data_v2_circuit_breaker

                record_data_v2_circuit_breaker(
                    query=task.query,
                    confidence=result.confidence,
                    threshold=threshold,
                    detail=(
                        f"sql={bool(result_ctx.compiled_sql)} "
                        f"rows={result_ctx.execution_row_count} "
                        f"err={result_ctx.execution_error or ''}"
                    ),
                    data_source_id=str(task.params.get("data_source_id") or ""),
                    trace_id=self._trace_id,
                    latency_ms=elapsed_ms,
                    resolution="v1_fallback_if_enabled",
                )
            except Exception as exc:
                logger.warning("data_v2_failure_memory_skipped", error=str(exc))
            raise LowConfidenceError(
                confidence=result.confidence,
                threshold=threshold,
                detail=f"sql={bool(result_ctx.compiled_sql)} rows={result_ctx.execution_row_count} err={result_ctx.execution_error or ''}",
            )

        # 9. 批评评估：可解释置信度（Phase 2.2）
        critic_enabled = bool(getattr(settings, "data_agent_v2_critic_enabled", True))
        if critic_enabled:
            result = self._apply_critic(task, result, result_ctx)

        # 10. 学习：模式提取 + 知识更新（Phase 3）
        learning_enabled = bool(getattr(settings, "data_agent_v2_learning_enabled", False))
        auto_learn = bool(getattr(settings, "data_agent_v2_auto_learning_enabled", True))
        if learning_enabled or auto_learn:
            result_ctx = await self._run_learning_pipeline(
                task, result, result_ctx, auto_mode=auto_learn and not learning_enabled
            )
            if result_ctx.learning_signals:
                result.metadata = dict(result.metadata or {})
                result.metadata["data_learning_signals"] = dict(result_ctx.learning_signals)

        if result.status == "success" and not result_ctx.execution_error:
            try:
                from kernel.agent_runtime.learning_hook import record_agent_learning_signal

                elapsed_ms = int((time.monotonic() - t0) * 1000)
                lr = await record_agent_learning_signal(
                    agent_type="data",
                    task_id=task.task_id,
                    session_id=str(task.session_id or ""),
                    passed=True,
                    confidence=float(result.confidence or 0.0),
                    evidence_quality=float(result.confidence or 0.0),
                    latency_ms=elapsed_ms,
                    metadata={
                        "query_type": "data_query",
                        "query_preview": (task.query or "")[:80],
                        "reflection_rounds": int(result_ctx.reflection_rounds or 0),
                        "row_count": int(result_ctx.execution_row_count or 0),
                    },
                )
                result.metadata = dict(result.metadata or {})
                result.metadata["runtime_learning"] = lr
            except Exception as exc:
                logger.debug("data_supervisor_learning_hook_skipped", error=str(exc))

        await self._record_event(self._trace_id, task, "complete",
                                 {"total_ms": int((time.monotonic() - t0) * 1000),
                                  "confidence": result.confidence,
                                  "status": result.status},
                                 status=result.status)
        return result

    # ── 步骤执行 ────────────────────────────────────────────────

    async def _run_knowledge_layer(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """执行 KnowledgeRetrieverAgent。"""
        own_session = None
        try:
            if not task.params.get("_db_session"):
                from infra.storage.database import AsyncSessionLocal
                own_session = AsyncSessionLocal()

            agent = self._tier2.get_agent("data_knowledge")
            task_params = {
                **task.params,
                "cognitive_context": ctx.to_dict(),
                "_db_session": task.params.get("_db_session") or own_session,
            }
            kb_task = TaskMessage(
                task_id=f"{task.task_id}_knowledge",
                agent_type="data_knowledge",
                query=ctx.query,
                params=task_params,
                session_id=task.session_id,
                user_id=task.user_id,
            )
            result = self._coerce_agent_result(await agent.execute(kb_task))
            return CognitiveContext.from_dict(
                result.metadata.get("cognitive_context", ctx.to_dict())
            )
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return ctx
        finally:
            if own_session is not None:
                try:
                    await own_session.close()
                except Exception as exc:
                    logger.warning("Supervisor operation failed", error=str(exc))

    async def _execute_dag(
        self, task: TaskMessage, ctx: CognitiveContext, dag: DagPlanSpec,
    ) -> CognitiveContext:
        """执行认知 DAG 并传递合并后的 CognitiveContext。

        通用 DagScheduler 仅转发静态节点参数。DataAgent V2
        需要每个依赖波次接收最新认知状态，因此 Supervisor
        保持相同 DAG 拓扑，但在波次间注入并合并上下文。
        """
        from infra.config.settings import settings

        timeout_sec = int(getattr(settings, "data_agent_v2_dag_parallel_timeout_sec", 30))
        pending = {n.node_id: n for n in dag.nodes}
        completed: set[str] = set()

        while pending:
            ready = [
                n for n in pending.values()
                if all(dep in completed for dep in n.depends_on)
            ]
            if not ready:
                unresolved = sorted(pending)
                await self._record_event(
                    self._trace_id, task, "dag_execute_error",
                    {"error": "unresolved_dependencies", "nodes": unresolved},
                    status="error",
                )
                break

            results = await asyncio.gather(
                *(self._run_dag_node(task, node, ctx, timeout_sec) for node in ready),
                return_exceptions=True,
            )

            for node, result in zip(ready, results, strict=False):
                pending.pop(node.node_id, None)
                completed.add(node.node_id)
                if isinstance(result, Exception):
                    await self._record_event(
                        self._trace_id, task, "dag_node_error",
                        {"node_id": node.node_id, "error": str(result)},
                        node_id=node.node_id,
                        status="error",
                    )
                    continue
                result_ctx_dict = (result.metadata or {}).get("cognitive_context", {})
                if result_ctx_dict:
                    ctx = self._merge_context(ctx, CognitiveContext.from_dict(result_ctx_dict))
                await self._record_event(
                    self._trace_id, task, "dag_node_complete",
                    {
                        "node_id": node.node_id,
                        "agent_type": result.agent_type,
                        "status": result.status,
                        "confidence": result.confidence,
                        "error": result.error or "",
                    },
                    node_id=node.node_id,
                    status=result.status,
                )

            if (
                ctx.intent
                and ctx.intent.get("intent_type") == "metadata"
                and ctx.compiled_sql
            ):
                pending.clear()
                await self._record_event(
                    self._trace_id, task, "dag_fast_path",
                    {"fast_path": "metadata"},
                    status="success",
                )

        return ctx

    async def _maybe_replan_after_verification_fail(
        self,
        task: TaskMessage,
        ctx: CognitiveContext,
        enabled_agents: dict[str, bool],
        is_metadata: bool,
    ) -> CognitiveContext:
        """Limited DAG replan when verification fails (error_classifier + critic hints)."""
        from infra.config.settings import settings

        if not bool(getattr(settings, "data_agent_v2_verification_replan_enabled", True)):
            return ctx
        max_replans = int(getattr(settings, "data_agent_v2_verification_replan_max", 2) or 2)
        max_replans = max(0, min(max_replans, 3))

        replan_round = 0
        while replan_round < max_replans:
            report = ctx.verification_report or {}
            if report.get("status") != "fail":
                break

            from agents.data_agent_v2.error_classifier import ErrorClassifier

            diagnoses = ErrorClassifier().classify_runtime_issue(
                rows=ctx.execution_rows or [],
                error=ctx.execution_error or "",
                verification_report=report,
                ctx=ctx,
            )
            repairable = any(getattr(d, "repairable", True) for d in diagnoses)
            if not repairable and diagnoses:
                break

            repair_prompt = ErrorClassifier().get_repair_prompt(diagnoses)
            ctx.metadata_extra = dict(ctx.metadata_extra or {})
            ctx.metadata_extra["verification_replan"] = {
                "round": replan_round + 1,
                "diagnosis_count": len(diagnoses),
                "categories": [getattr(d.category, "value", str(d.category)) for d in diagnoses[:6]],
            }
            if repair_prompt:
                ctx.metadata_extra["verification_repair_guidance"] = repair_prompt[:2000]

            try:
                from agents.data_agent_v2.data_critic import DataCriticAdapter

                critic = DataCriticAdapter()
                enriched = critic.enrich_result(
                    query=task.query,
                    content="",
                    confidence=0.3,
                    rows=ctx.execution_rows,
                    sql=ctx.compiled_sql or "",
                    error="SQL verification failed",
                    verification_report=report,
                )
                if enriched.get("critic_need_fix"):
                    ctx.metadata_extra["critic_replan_hint"] = True
            except Exception as exc:
                logger.debug("verification_replan_critic_skipped", error=str(exc))

            ctx.compiled_sql = None
            ctx.verification_report = None
            ctx.execution_error = None
            ctx.execution_rows = None
            ctx.execution_row_count = 0

            dag = build_cognitive_dag(
                query=ctx.query,
                enabled=enabled_agents,
                parallel=bool(getattr(settings, "data_agent_v2_dag_parallel_enabled", True)),
                is_metadata=is_metadata,
            )
            ctx = await self._execute_dag(task, ctx, dag)
            replan_round += 1
            await self._record_event(
                self._trace_id,
                task,
                "verification_replan",
                {
                    "round": replan_round,
                    "status": (ctx.verification_report or {}).get("status", ""),
                    "diagnoses": len(diagnoses),
                },
                status="success",
            )

        if replan_round > 0:
            ctx.metadata_extra = dict(ctx.metadata_extra or {})
            ctx.metadata_extra["verification_replan_total"] = replan_round
        return ctx

    async def _run_dag_node(
        self,
        task: TaskMessage,
        node: DagNodeSpec,
        ctx: CognitiveContext,
        timeout_sec: int,
    ) -> AgentResult:
        """使用当前认知上下文运行一个 V2 DAG 节点。"""
        agent = self._tier2.get_agent(node.agent_type)

        params = {
            **task.params,
            **(node.params or {}),
            "cognitive_context": ctx.to_dict(),
            "session_id": task.session_id or "",
            "user_id": task.user_id or "",
        }
        msg = TaskMessage(
            task_id=f"{task.task_id}_{node.node_id}",
            agent_type=node.agent_type,
            query=node.query,
            params=params,
            session_id=task.session_id,
            user_id=task.user_id,
        )
        result = await asyncio.wait_for(agent.execute(msg), timeout=timeout_sec)
        return self._coerce_agent_result(result)

    async def _execute_sql(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """若校验通过则执行编译后的 SQL。"""
        if not ctx.compiled_sql:
            ctx.execution_error = "no compiled SQL generated by DataAgent V2"
            return ctx

        report = ctx.verification_report or {}
        if report.get("status") == "fail":
            from agents.data_agent_v2.turn_metadata import build_error_diagnosis_metadata

            ctx.execution_error = "SQL verification failed"
            ctx.metadata_extra = dict(ctx.metadata_extra or {})
            ctx.metadata_extra.update(build_error_diagnosis_metadata(ctx, error=ctx.execution_error))
            from agents.data_agent_v2.turn_metadata import verification_turn_metadata

            ctx.metadata_extra.update(verification_turn_metadata(report))
            return ctx

        try:
            dsn = task.params.get("_dsn", "")
            if not dsn:
                ctx.execution_error = (
                    "data source connection is not available — "
                    "check data_source_id and that the datasource record exists"
                )
                return ctx

            from execution.data.sql_executor import SQLExecutor
            from kernel.data_cognition.sql_validator import SQLValidator

            safe_sql = SQLValidator(default_limit=100).validate(ctx.compiled_sql)
            rows = await SQLExecutor().run_on_dsn(dsn, safe_sql)

            ctx.execution_rows = rows
            ctx.execution_row_count = len(rows)
            ctx.compiled_sql = safe_sql
            ctx.reflection_rounds = 0  # 将由 ReflectionAgent 按需设置

        except Exception as exc:
            from execution.data.database_hosts import format_database_connection_error

            from agents.data_agent_v2.turn_metadata import build_error_diagnosis_metadata

            ctx.execution_error = format_database_connection_error(
                exc,
                configured_host=str(task.params.get("_db_host") or ""),
                port=task.params.get("_db_port"),
                database=str(task.params.get("_db_database") or "") or None,
            )
            ctx.metadata_extra = dict(ctx.metadata_extra or {})
            ctx.metadata_extra.update(
                build_error_diagnosis_metadata(ctx, error=ctx.execution_error, rows=[])
            )

        return ctx

    # ── 辅助方法 ────────────────────────────────────────────────────────

    async def _run_reflection(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """运行 ReflectionAgent 观察结果并尝试修复。"""
        try:
            from agents.data_agent_v2.reflection_agent import ReflectionAgent

            agent = ReflectionAgent()
            agent_task = TaskMessage(
                task_id=f"{task.task_id}_reflection",
                agent_type="data_reflection",
                query=ctx.query,
                params={
                    "cognitive_context": ctx.to_dict(),
                    "query": ctx.query,
                    "schema_hint": ctx.schema_hint,
                },
                session_id=task.session_id,
                user_id=task.user_id,
            )
            result = self._coerce_agent_result(await agent.execute(agent_task))
            return CognitiveContext.from_dict(
                result.metadata.get("cognitive_context", ctx.to_dict())
            )
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return ctx

    def _apply_critic(
        self, task: TaskMessage, result: AgentResult, ctx: CognitiveContext
    ) -> AgentResult:
        """应用 DataCriticAdapter 进行可解释置信度与质量评估。"""
        try:
            from agents.data_agent_v2.data_critic import DataCriticAdapter

            critic = DataCriticAdapter()
            enriched = critic.enrich_result(
                query=task.query,
                content=result.content,
                confidence=result.confidence,
                rows=ctx.execution_rows,
                sql=ctx.compiled_sql or "",
                error=ctx.execution_error or "",
                verification_report=ctx.verification_report,
            )

            result.content = enriched["content"]
            result.confidence = enriched["confidence"]

            if result.metadata is None:
                result.metadata = {}
            result.metadata["confidence_breakdown"] = enriched["confidence_breakdown"]
            result.metadata["confidence_explanation"] = enriched["confidence_explanation"]
            result.metadata["critic_feedback"] = enriched["critic_feedback"]

            if result.agent_trace is None:
                result.agent_trace = {}
            result.agent_trace["critic_need_fix"] = enriched.get("critic_need_fix", False)
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))

        return result

    # ── 高级分析（Phase 4）────────────────────────────────────

    def _expand_skills(self, dag: DagPlanSpec, ctx: CognitiveContext) -> DagPlanSpec:
        """用分析技能模板扩展 DAG。"""
        try:
            from agents.data_agent_v2.skills_engine import SkillsEngine

            engine = SkillsEngine()
            # 使用第一个匹配的技能
            skill = ctx.matched_skills[0]
            return engine.expand(skill, dag, ctx)
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return dag

    async def _run_advanced_analytics(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """对查询结果运行高级分析 Agent。

        模式（由 data_agent_v2_advanced_analytics_mode 控制）：
        - "off"：跳过所有高级分析
        - "manual"：使用各独立特性开关（向后兼容）
        - "auto"：根据意图和查询关键词自动决定运行哪些 Agent
        """
        from infra.config.settings import settings

        mode = str(getattr(settings, "data_agent_v2_advanced_analytics_mode", "manual") or "manual")

        if mode == "off":
            ctx.metadata_extra = dict(ctx.metadata_extra or {})
            ctx.metadata_extra["advanced_analytics"] = {
                "mode": "off",
                "skipped": True,
                "degraded": False,
            }
            return ctx

        if mode == "auto":
            statistical_enabled, insight_enabled, viz_enabled = self._resolve_auto_analytics(ctx)
        else:
            # "manual" 模式 — 使用各独立开关
            statistical_enabled = bool(getattr(settings, "data_agent_v2_statistical_enabled", False))
            insight_enabled = bool(getattr(settings, "data_agent_v2_insight_enabled", False))
            viz_enabled = bool(getattr(settings, "data_agent_v2_visualization_enabled", False))

        # 统计分析（Phase 4.1）
        if statistical_enabled:
            ctx = await self._run_agent(
                task, ctx, "data_statistical",
                "agents.data_agent_v2.statistical_agent", "StatisticalAgent",
            )

        # 洞察生成（Phase 4.2）
        if insight_enabled:
            ctx = await self._run_agent(
                task, ctx, "data_insight",
                "agents.data_agent_v2.insight_agent", "InsightAgent",
            )

        # 可视化推荐（Phase 4.3）
        if viz_enabled:
            ctx = await self._run_agent(
                task, ctx, "data_visualization",
                "agents.data_agent_v2.visualization_agent", "VisualizationAgent",
            )

        ctx.metadata_extra = dict(ctx.metadata_extra or {})
        ctx.metadata_extra["advanced_analytics"] = {
            "mode": mode,
            "statistical_ran": bool(statistical_enabled and ctx.statistical_report),
            "insight_ran": bool(insight_enabled and ctx.insights),
            "visualization_ran": bool(viz_enabled and ctx.visualization_config),
            "statistical_requested": statistical_enabled,
            "insight_requested": insight_enabled,
            "visualization_requested": viz_enabled,
            "degraded": mode == "auto" and not any(
                [statistical_enabled, insight_enabled, viz_enabled]
            ),
        }
        return ctx

    def _resolve_auto_analytics(self, ctx: CognitiveContext) -> tuple[bool, bool, bool]:
        """根据意图和查询决定运行哪些高级分析。

        返回 (statistical_enabled, insight_enabled, visualization_enabled)。
        """
        query_lower = (ctx.query or "").lower()
        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""

        # 适合统计分析和洞察的意图类型
        analytical_intents = {
            "trend", "comparison", "anomaly_detection",
            "ranking", "composition", "distribution",
            "aggregation",  # COUNT/SUM by group also benefits from stats & insights
        }

        # 表示需要趋势/统计分析的关键词
        trend_keywords = ["趋势", "走势", "变化", "环比", "同比", "增长", "下降", "上升", "下滑"]
        cause_keywords = ["原因", "为什么", "影响因素", "分析", "驱动", "关联", "影响"]
        chart_keywords = ["图", "chart", "图表", "可视化", "折线", "柱状", "饼图"]
        agg_keywords = ["统计", "汇总", "各", "每个", "按", "合计", "数量", "人数"]

        need_statistical = (
            intent_type in analytical_intents
            or any(kw in query_lower for kw in trend_keywords)
            or any(kw in query_lower for kw in agg_keywords)
        )
        need_insight = (
            intent_type in analytical_intents
            or any(kw in query_lower for kw in cause_keywords)
            or any(kw in query_lower for kw in trend_keywords)
            or any(kw in query_lower for kw in agg_keywords)
        )
        need_viz = (
            intent_type in {"trend", "comparison", "composition", "distribution", "ranking", "aggregation"}
            or any(kw in query_lower for kw in chart_keywords)
        )

        return need_statistical, need_insight, need_viz

    async def _run_agent(
        self,
        task: TaskMessage,
        ctx: CognitiveContext,
        agent_type: str,
        module_path: str,
        class_name: str,
    ) -> CognitiveContext:
        """通过模块路径和类名运行单个 Agent。"""
        try:
            import importlib
            mod = importlib.import_module(module_path)
            agent_cls = getattr(mod, class_name)
            agent = agent_cls()
            agent_task = TaskMessage(
                task_id=f"{task.task_id}_{agent_type}",
                agent_type=agent_type,
                query=ctx.query,
                params={"cognitive_context": ctx.to_dict()},
                session_id=task.session_id,
                user_id=task.user_id,
            )
            result = self._coerce_agent_result(await agent.execute(agent_task))
            return CognitiveContext.from_dict(
                result.metadata.get("cognitive_context", ctx.to_dict())
            )
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return ctx

    # ── 学习层（Phase 3）────────────────────────────────────────

    async def _run_learning_pipeline(
        self,
        task: TaskMessage,
        result: AgentResult,
        ctx: CognitiveContext,
        *,
        auto_mode: bool = False,
    ) -> CognitiveContext:
        """运行学习流水线：反馈收集 → 模式提取 → 知识更新。"""
        from infra.config.settings import settings

        # 确保学习 Agent 可用数据库会话
        _own_session = None
        if not task.params.get("_db_session"):
            try:
                from infra.storage.database import AsyncSessionLocal
                _own_session = AsyncSessionLocal()
                task.params["_db_session"] = _own_session
            except Exception as exc:
                logger.warning("Supervisor operation failed", error=str(exc))

        try:
            # 10a. 若任务参数中提供了反馈则收集
            feedback = task.params.get("feedback")
            if feedback:
                ctx = await self._run_feedback_collector(task, ctx, feedback)
            elif auto_mode and result.status == "success" and ctx.compiled_sql and not ctx.execution_error:
                ctx = await self._run_feedback_collector(
                    task,
                    ctx,
                    {
                        "type": "like",
                        "rating": 5,
                        "source": "auto_success",
                        "reflection_rounds": ctx.reflection_rounds,
                    },
                )

            # 10b. 从成功查询中提取模式
            pattern_enabled = bool(getattr(settings, "data_agent_v2_pattern_memory_enabled", False))
            run_pattern = pattern_enabled or (
                auto_mode
                and result.status == "success"
                and ctx.compiled_sql
                and not ctx.execution_error
                and float(result.confidence or 0) >= 0.65
            )
            if run_pattern and result.status == "success" and ctx.compiled_sql:
                ctx = await self._run_pattern_extractor(task, ctx, result)

            # 10c. 若存在学习信号则应用知识更新
            if ctx.learning_signals:
                ctx = await self._run_knowledge_updater(task, ctx)
            elif auto_mode and result.status == "success" and ctx.compiled_sql:
                ctx.learning_signals = (ctx.learning_signals or {}) | {
                    "feedback_type": "auto_success",
                    "feedback_action": "reinforce_pattern",
                    "confidence_impact": 0.03,
                }
                ctx = await self._run_knowledge_updater(task, ctx)
        finally:
            if _own_session is not None:
                try:
                    await _own_session.close()
                except Exception as exc:
                    logger.warning("Supervisor operation failed", error=str(exc))
                task.params.pop("_db_session", None)

        return ctx

    async def _run_feedback_collector(
        self, task: TaskMessage, ctx: CognitiveContext, feedback: dict
    ) -> CognitiveContext:
        """运行 FeedbackCollectorAgent 分类并存储用户反馈。"""
        try:
            from agents.data_agent_v2.feedback_collector import FeedbackCollectorAgent

            agent = FeedbackCollectorAgent()
            agent_task = TaskMessage(
                task_id=f"{task.task_id}_feedback",
                agent_type="data_feedback_collector",
                query=ctx.query,
                params={
                    "cognitive_context": ctx.to_dict(),
                    "feedback": feedback,
                },
                session_id=task.session_id,
                user_id=task.user_id,
            )
            result = self._coerce_agent_result(await agent.execute(agent_task))
            return CognitiveContext.from_dict(
                result.metadata.get("cognitive_context", ctx.to_dict())
            )
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return ctx

    async def _run_pattern_extractor(
        self, task: TaskMessage, ctx: CognitiveContext, result: AgentResult
    ) -> CognitiveContext:
        """运行 PatternExtractorAgent 存储成功的查询模式。"""
        try:
            from agents.data_agent_v2.pattern_extractor import PatternExtractorAgent

            agent = PatternExtractorAgent()
            agent_task = TaskMessage(
                task_id=f"{task.task_id}_pattern",
                agent_type="data_pattern_extractor",
                query=ctx.query,
                params={
                    "cognitive_context": ctx.to_dict(),
                    "final_confidence": result.confidence,
                    "_db_session": task.params.get("_db_session"),
                },
                session_id=task.session_id,
                user_id=task.user_id,
            )
            agent_result = self._coerce_agent_result(await agent.execute(agent_task))
            return CognitiveContext.from_dict(
                agent_result.metadata.get("cognitive_context", ctx.to_dict())
            )
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return ctx

    async def _run_knowledge_updater(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """运行 KnowledgeUpdaterAgent 将学习应用到知识资产。"""
        try:
            from agents.data_agent_v2.knowledge_updater import KnowledgeUpdaterAgent

            agent = KnowledgeUpdaterAgent()
            agent_task = TaskMessage(
                task_id=f"{task.task_id}_knowledge_updater",
                agent_type="data_knowledge_updater",
                query=ctx.query,
                params={
                    "cognitive_context": ctx.to_dict(),
                    "_db_session": task.params.get("_db_session"),
                },
                session_id=task.session_id,
                user_id=task.user_id,
            )
            agent_result = self._coerce_agent_result(await agent.execute(agent_task))
            return CognitiveContext.from_dict(
                agent_result.metadata.get("cognitive_context", ctx.to_dict())
            )
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return ctx

    # ── 事件记录（Phase P2：认知审计轨迹）─────────────────────

    async def _record_event(
        self,
        trace_id: str,
        task: TaskMessage,
        step: str,
        payload: dict | None = None,
        node_id: str | None = None,
        status: str = "start",
        duration_ms: int | None = None,
    ) -> None:
        """即发即弃的认知事件记录。

        仅在 DATA_AGENT_V2_COGNITIVE_EVENTS_ENABLED=true 时写入。
        失败静默忽略 — 审计事件不得阻塞流水线。
        """
        try:
            from infra.config.settings import settings
            if not bool(getattr(settings, "data_agent_v2_cognitive_events_enabled", False)):
                return
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return

        try:
            from infra.storage.database import AsyncSessionLocal
            from infra.storage.models import CognitiveEvent

            async with AsyncSessionLocal() as db:
                event = CognitiveEvent(
                    trace_id=trace_id,
                    query_id=task.task_id,
                    step=step,
                    node_id=node_id,
                    status=status,
                    payload=payload,
                    duration_ms=duration_ms,
                )
                db.add(event)
                await db.commit()
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))

    # ── 上下文初始化 ─────────────────────────────────────────

    def _init_context(self, task: TaskMessage) -> CognitiveContext:
        """从 TaskMessage 初始化新的 CognitiveContext。

        若提供了 clarify_context（多轮追问），将其与原始查询合并，
        使下游 Agent 能看到完整上下文。
        """
        query = task.query
        miq = str(task.params.get("memory_injection_query", "") or "").strip()
        if miq:
            query = miq
        mtr = task.params.get("multi_turn_resolution")
        if isinstance(mtr, dict):
            rq = str(mtr.get("resolved_query", "") or "").strip()
            if rq and not miq:
                query = rq
        clarify_context = str(task.params.get("clarify_context", "") or "").strip()
        if clarify_context:
            query = f"原始问题：{query}\n用户补充信息：{clarify_context}"
        pref = str(task.params.get("user_preference_context_block", "") or "").strip()
        if pref:
            query = f"{query}\n\n【用户偏好】\n{pref[:1200]}"

        mtc = task.params.get("multi_turn_constraints")
        if isinstance(mtc, dict) and mtc:
            import json

            query = f"{query}\n\n【多轮约束】\n{json.dumps(mtc, ensure_ascii=False)[:800]}"

        dsc = task.params.get("data_source_context")
        if isinstance(dsc, dict) and not task.params.get("data_source_id"):
            ds_id = str(dsc.get("data_source_id") or dsc.get("id") or "")
        else:
            ds_id = str(task.params.get("data_source_id", "") or "")
        from kernel.clarification_enrichment import enrichment_blocks_from_params

        ctx = CognitiveContext(
            query=query,
            data_source_id=ds_id,
            dialect=task.params.get("dialect", "postgresql"),
            schema_hint=task.params.get("schema_hint", ""),
            table_names=task.params.get("table_names", []),
            table_columns=task.params.get("table_columns", {}),
            semantic_config=task.params.get("semantic_config", {}),
            compiled_sql=str(task.params.get("sql", "") or "").strip() or None,
            clarify_context=clarify_context,
        )
        block = enrichment_blocks_from_params(dict(task.params or {}))
        if block:
            setattr(ctx, "clarification_enrichment_block", block)
        return ctx

    async def _load_datasource_metadata(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> None:
        """若尚未提供则加载数据源元数据。"""
        if ctx.table_names and ctx.table_columns and not ctx.data_source_id:
            return

        if not ctx.data_source_id:
            return

        try:
            from execution.data.db_router import DBConnectionInfo, DBRouter
            from infra.security.data_source_secrets import decrypt_data_source_secret
            from sqlalchemy import select
            from infra.storage.database import AsyncSessionLocal
            from infra.storage.models import DataSource, DataSourceSchema
            from kernel.data_cognition.sql_dialect import detect_sql_dialect

            async with AsyncSessionLocal() as db:
                ds_result = await db.execute(
                    select(DataSource).where(DataSource.id == ctx.data_source_id)
                )
                ds = ds_result.scalar_one_or_none()
                if ds:
                    dialect = detect_sql_dialect(ds.source_type)
                    ctx.dialect = dialect.name
                    task.params["_db_host"] = ds.host
                    task.params["_db_port"] = ds.port
                    task.params["_db_database"] = ds.database
                    task.params["_dsn"] = DBRouter().build_dsn(
                        DBConnectionInfo(
                            source_type=ds.source_type,
                            host=ds.host,
                            port=ds.port,
                            database=ds.database,
                            username=ds.username,
                            password=decrypt_data_source_secret(ds.password_encrypted),
                        )
                    )

                result = await db.execute(
                    select(DataSourceSchema).where(
                        DataSourceSchema.data_source_id == ctx.data_source_id
                    )
                )
                schema_row = result.scalar()

                if schema_row:
                    if not ctx.table_names:
                        schema_dict = json.loads(schema_row.schema_json or "{}")
                        tables = schema_dict.get("tables", [])
                        ctx.table_names = [t.get("name", "") for t in tables]
                        ctx.table_columns = {
                            t.get("name", ""): [c.get("name", "") for c in t.get("columns", [])]
                            for t in tables
                        }
                    if not ctx.schema_hint:
                        ctx.schema_hint = schema_row.schema_json or ""
                    if not ctx.semantic_config:
                        ctx.semantic_config = schema_row.semantic_mappings or {}

        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))

    def _merge_context(
        self, base: CognitiveContext, update: CognitiveContext
    ) -> CognitiveContext:
        """合并子 Agent 上下文而不覆盖先前 Agent 的输出。"""
        merged = base.to_dict()
        for key, value in update.to_dict().items():
            if value is None:
                continue
            if isinstance(value, (list, dict, str)) and not value:
                continue
            merged[key] = value
        return CognitiveContext.from_dict(merged)

    def _coerce_agent_result(self, result: AgentResult | dict[str, Any]) -> AgentResult:
        """在 Supervisor 边界将子 Agent 结果归一化为 AgentResult。"""
        if isinstance(result, AgentResult):
            return result
        if isinstance(result, dict):
            return AgentResult(**result)
        raise TypeError(f"unsupported agent result type: {type(result).__name__}")

    def _build_result_refs(
        self, task: TaskMessage, ctx: CognitiveContext, rows: list[dict], sql: str
    ) -> list[dict[str, Any]]:
        """构建与编排器/UI 兼容的结果引用。"""
        if not sql:
            return []
        try:
            from kernel.result_reference import ResultRef, serialize_refs

            row_count = len(rows)
            return serialize_refs([
                ResultRef(
                    ref_id=f"sql:{task.task_id}",
                    type="sql",
                    title=f"SQL: {task.query[:60]}",
                    summary=f"Generated SQL ({len(sql)} chars, {row_count} rows)",
                    payload={"sql": sql, "dialect": ctx.dialect, "row_count": row_count},
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
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return []

    def _build_final_result(
        self, task: TaskMessage, ctx: CognitiveContext, t0: float
    ) -> AgentResult:
        """从 CognitiveContext 构建最终 AgentResult。"""
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        sql = ctx.compiled_sql or ""
        rows = ctx.execution_rows or []
        error = ctx.execution_error
        result_refs = self._build_result_refs(task, ctx, rows, sql)

        if error:
            from agents.data_agent_v2.turn_metadata import (
                build_error_diagnosis_metadata,
                verification_turn_metadata,
            )

            err_meta = {
                "sql": sql,
                "rows": rows[:20],
                "row_count": len(rows),
                "data_source_id": ctx.data_source_id,
                "mode": "data_agent_v2",
                "verification_report": ctx.verification_report,
                "result_refs": result_refs,
                "turn_outcome": "error",
                "pipeline_stage": "sql_execute",
            }
            if ctx.metadata_extra:
                err_meta.update(ctx.metadata_extra)
            elif not err_meta.get("error_diagnosis"):
                err_meta.update(build_error_diagnosis_metadata(ctx, error=error, rows=rows))
            if ctx.verification_report:
                err_meta.update(verification_turn_metadata(ctx.verification_report))
            try:
                from services.data_intelligence_runtime import attach_data_intelligence_to_metadata

                err_meta = attach_data_intelligence_to_metadata(
                    err_meta,
                    query=task.query,
                    sql=sql,
                    row_count=len(rows),
                )
            except Exception as exc:
                logger.warning("data_intelligence_attach_skipped", error=str(exc))
            return AgentResult(
                task_id=task.task_id,
                agent_type="data",
                status="error",
                content=f"数据查询执行失败：{error}",
                confidence=0.0,
                error=error,
                metadata=err_meta,
                agent_trace={
                    "elapsed_ms": elapsed_ms,
                    "pipeline": "data_agent_v2",
                    "error": error,
                },
            )

        # 构建解释（包含高级分析，若可用）
        content = self._format_rows_content(rows, sql, ctx)

        # 计算置信度（包含分析加成）
        confidence = self._compute_confidence(ctx, rows, sql)

        # 收集高级分析的证据
        evidence = [{
            "source": "data_query",
            "source_type": "sql",
            "payload": {
                "sql": sql,
                "row_count": len(rows),
                "verification": ctx.verification_report,
            },
            "credibility_score": 0.90,
            "relevance_score": 1.0,
            "acquisition_cost": elapsed_ms / 1000.0,
            "provenance": "data_agent_v2",
        }]

        if ctx.statistical_report:
            evidence.append({
                "source": "statistical_analysis",
                "source_type": "analysis",
                "payload": {"numeric_cols": len(ctx.statistical_report.get("numeric_columns", []))},
                "credibility_score": 0.95,
                "relevance_score": 0.85,
            })

        if ctx.insights:
            evidence.append({
                "source": "data_insights",
                "source_type": "analysis",
                "payload": {"observation_count": len(ctx.insights.get("observations", []))},
                "credibility_score": 0.80,
                "relevance_score": 0.90,
            })

        if ctx.visualization_config:
            evidence.append({
                "source": "visualization",
                "source_type": "analysis",
                "payload": {"chart_type": ctx.visualization_config.get("chart_type", "")},
                "credibility_score": 0.90,
                "relevance_score": 0.85,
            })

        from agents.data_agent_v2.turn_metadata import verification_turn_metadata

        v2_meta = {
            "rows": rows[:20],
            "row_count": len(rows),
            "sql": sql,
            "data_source_id": ctx.data_source_id,
            "mode": "data_agent_v2",
            "verification_report": ctx.verification_report,
            "intent": ctx.intent,
            "metrics_used": [m.get("mention", "") for m in (ctx.metrics or [])],
            "entities_used": [e.get("mapped_table", "") for e in (ctx.entities or [])],
            "statistical_report": ctx.statistical_report,
            "insights": ctx.insights,
            "visualization_config": ctx.visualization_config,
            "result_refs": result_refs,
            "turn_outcome": "success",
            "pipeline_stage": "complete",
        }
        if ctx.verification_report:
            v2_meta.update(verification_turn_metadata(ctx.verification_report))
        if ctx.metadata_extra:
            v2_meta.update(ctx.metadata_extra)
        if not rows and sql:
            from agents.data_agent_v2.turn_metadata import build_error_diagnosis_metadata

            v2_meta.update(build_error_diagnosis_metadata(ctx, error="", rows=rows))
        try:
            from services.data_intelligence_runtime import attach_data_intelligence_to_metadata

            v2_meta = attach_data_intelligence_to_metadata(
                v2_meta,
                query=task.query,
                sql=sql or "",
                row_count=len(rows),
                metric_names=[m.get("mention", "") for m in (ctx.metrics or []) if m.get("mention")],
            )
        except Exception as exc:
            logger.warning("data_intelligence_attach_skipped", error=str(exc))
        from agents.data_agent_v2.turn_metadata import build_data_success_evidence_objects

        evidence_objects = build_data_success_evidence_objects(
            task_id=task.task_id,
            sql=sql,
            rows=rows,
            confidence=confidence,
            elapsed_ms=elapsed_ms,
            verification_report=ctx.verification_report,
            evidence_dicts=evidence,
        )
        return AgentResult(
            task_id=task.task_id,
            agent_type="data",
            status="success",
            content=content,
            confidence=confidence,
            metadata=v2_meta,
            evidence=evidence,
            evidence_objects=evidence_objects,
            agent_trace={
                "elapsed_ms": elapsed_ms,
                "pipeline": "data_agent_v2",
                "intent_type": ctx.intent.get("intent_type", "") if ctx.intent else "",
                "metric_count": len(ctx.metrics or []),
                "entity_count": len(ctx.entities or []),
                "verification_status": ctx.verification_report.get("status", "") if ctx.verification_report else "",
                "pattern_hit": ctx.pattern_hit is not None,
                "has_statistics": ctx.statistical_report is not None,
                "has_insights": ctx.insights is not None,
                "has_visualization": ctx.visualization_config is not None,
            },
        )

    def _compute_confidence(
        self, ctx: CognitiveContext, rows: list, sql: str
    ) -> float:
        """从所有流水线信号计算总体置信度。"""
        confidence = 0.60

        if sql:
            confidence += 0.10
        if rows:
            confidence += 0.10
        if len(rows) > 1:
            confidence += 0.05
        if ctx.metrics:
            confidence += 0.05
        if ctx.entities:
            confidence += 0.05
        if ctx.verification_report and ctx.verification_report.get("status") == "pass":
            confidence += 0.05
        # 高级分析加成
        if ctx.statistical_report:
            confidence += 0.03
        if ctx.insights:
            ic = ctx.insights.get("confidence", 0)
            if isinstance(ic, (int, float)) and ic > 0.7:
                confidence += 0.03
        if ctx.visualization_config:
            confidence += 0.02

        # 校验警告惩罚
        if ctx.verification_report:
            issues = ctx.verification_report.get("issues", [])
            confidence -= 0.02 * len([i for i in issues if i.get("severity") in ("high", "critical")])

        return max(0.1, min(0.99, confidence))

    def _format_rows_content(
        self, rows: list[dict], sql: str, ctx: CognitiveContext | None = None
    ) -> str:
        """将查询结果格式化为带分析的人类可读内容。"""
        if not rows:
            return "查询未返回数据。"

        query_text = ctx.query if ctx else ""
        parts = [f"查询「{query_text}」返回 {len(rows)} 行数据。"]

        if sql:
            parts.append(f"执行SQL：\n```sql\n{sql}\n```")

        # 若可用则附加洞察
        has_insight_summary = ctx and ctx.insights and ctx.insights.get("summary")
        if has_insight_summary:
            insights = ctx.insights
            parts.append(f"\n{insights['summary']}")
            observations = insights.get("observations", [])
            if observations:
                parts.append("\n关键发现:\n" + "\n".join(f"• {o}" for o in observations[:5]))
            recommendations = insights.get("recommendations", [])
            if recommendations:
                parts.append("\n建议:\n" + "\n".join(f"→ {r}" for r in recommendations[:3]))

        # 若可用则附加统计摘要（无洞察摘要时）
        if ctx and ctx.statistical_report and not has_insight_summary:
            stats = ctx.statistical_report
            trends = stats.get("trends", {})
            if trends:
                trend_parts = [
                    f"{col}: {t.get('direction', '?')} ({t.get('change_pct', '?')}%)"
                    for col, t in trends.items()
                ]
                parts.append("\n趋势:\n" + "\n".join(f"• {tp}" for tp in trend_parts))

            outliers = stats.get("outliers", {})
            total_outliers = sum(len(v) for v in outliers.values())
            if total_outliers > 0:
                parts.append(f"\n检测到 {total_outliers} 个异常值")

        # 无高级分析可用时的回退
        if ctx and not has_insight_summary and not ctx.statistical_report:
            parts.append(self._build_fallback_description(ctx, rows))

        return "\n\n".join(parts)

    def _build_fallback_description(
        self, ctx: CognitiveContext, rows: list[dict]
    ) -> str:
        """在高级分析不可用时构建有用的描述。"""
        fallback_parts = []

        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""

        # 将意图类型映射为中文描述
        intent_labels = {
            "trend": "趋势分析",
            "comparison": "对比分析",
            "ranking": "排名查询",
            "distribution": "分布查询",
            "composition": "构成分析",
            "anomaly_detection": "异常检测",
        }
        intent_label = intent_labels.get(intent_type, "")

        if intent_label:
            fallback_parts.append(f"这是一个{intent_label}类查询。")

        # 检查查询是否需要趋势/原因分析但无法满足
        query_lower = (ctx.query or "").lower()
        needs_trend = any(kw in query_lower for kw in ["趋势", "走势", "变化", "环比", "同比"])
        needs_cause = any(kw in query_lower for kw in ["原因", "为什么", "影响因素", "分析"])

        if needs_trend:
            # 检查 schema 是否有时间列
            time_cols = self._detect_time_columns(ctx)
            if time_cols:
                fallback_parts.append(
                    f"趋势分析需要时间维度，该数据源可用的时间字段包括：{', '.join(time_cols[:5])}。"
                    f"当前结果仅展示分布情况，趋势分析需要高级分析功能（StatisticalAgent）的支持。"
                )
            else:
                fallback_parts.append(
                    "当前结果可回答数据分布情况，但趋势分析需要时间字段（如 created_at、updated_at、stat_date 等）。"
                    "该表中未检测到明确的时间列，请确认使用哪个字段作为时间维度。"
                )

        if needs_cause:
            columns = list(rows[0].keys()) if rows else []
            fallback_parts.append(
                f"原因分析需要 InsightAgent 基于统计特征和业务语义进行推断。"
                f"当前可用维度：{', '.join(columns[:10])}。"
                "要启用自动原因分析，请开启 data_agent_v2_insight_enabled 配置项。"
            )

        if not fallback_parts:
            columns = list(rows[0].keys()) if rows else []
            fallback_parts.append(f"结果包含 {len(columns)} 个字段：{', '.join(columns[:15])}。")
            fallback_parts.append("要获取趋势、原因分析和图表建议，请启用高级分析功能。")

        return "\n".join(f"• {p}" for p in fallback_parts)

    def _detect_time_columns(self, ctx: CognitiveContext) -> list[str]:
        """从 schema 和查询上下文检测可能的时间列。"""
        time_keywords = [
            "time", "date", "timestamp", "created", "updated", "modified",
            "时间", "日期", "创建", "更新", "修改",
            "at", "day", "month", "year", "week",
        ]
        time_cols = []
        for col_list in (ctx.table_columns or {}).values():
            for col in col_list:
                col_lower = col.lower()
                if any(kw in col_lower for kw in time_keywords):
                    if col not in time_cols:
                        time_cols.append(col)
        return time_cols

    # ── 澄清门控 ──────────────────────────────────────────────

    async def _check_clarification(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> dict[str, Any] | None:
        """检查查询是否过于模糊需要澄清提问。

        若需要澄清则返回 ClarificationQuestion 字典，
        若查询足够清晰可继续执行则返回 None。
        """
        try:
            from kernel.clarification_gate import DataClarificationGate

            gate = DataClarificationGate()
            detect_result = gate.detect(ctx)
            if not detect_result.get("needs_clarification"):
                return None

            question = await gate.generate_question(
                ctx.query, detect_result, ctx
            )

            return asdict(question)
        except Exception as exc:
            logger.warning("Clarification check failed", error=str(exc))
            return None

    def _build_clarification_result(
        self, task: TaskMessage, ctx: CognitiveContext, t0: float
    ) -> AgentResult:
        """构建携带澄清提问的 AgentResult。

        此操作短路正常流水线 — 不执行 SQL。
        前端渲染澄清卡片而非结果表格。
        """
        clarification = ctx.clarification or {}
        question_text = clarification.get("question_text", "")
        suggested = clarification.get("suggested_options", [])

        content_parts = [question_text]
        if suggested:
            content_parts.append("\n\n你可以尝试以下方向：\n" + "\n".join(
                f"{i}. {opt}" for i, opt in enumerate(suggested, 1)
            ))
        content = "\n".join(content_parts)

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        from agents.data_agent_v2.turn_metadata import clarification_turn_metadata

        clar_meta = {
            "rows": [],
            "row_count": 0,
            "sql": "",
            "data_source_id": ctx.data_source_id,
            "mode": "data_agent_v2",
            "intent": ctx.intent,
            "result_refs": [],
            **clarification_turn_metadata(clarification),
        }
        return AgentResult(
            task_id=task.task_id,
            agent_type="data",
            status="success",
            content=content,
            confidence=0.15,
            metadata=clar_meta,
            evidence=[{
                "source": "clarification_gate",
                "source_type": "clarification",
                "payload": {
                    "reason": "query too vague, asking for clarification",
                    "missing_entities": clarification.get("missing_entities", []),
                    "suggested_count": len(suggested),
                },
                "credibility_score": 1.0,
                "relevance_score": 1.0,
            }],
            agent_trace={
                "elapsed_ms": elapsed_ms,
                "pipeline": "data_agent_v2",
                "clarification": True,
            },
        )
