"""
DataAgentV2Supervisor — thin coordinator that orchestrates the cognitive pipeline.

Responsibilities:
1. Initialize cognitive context from task parameters
2. Run Knowledge Layer (KnowledgeRetrieverAgent)
3. Build DAG from CognitiveContext + feature flags
4. Execute DAG via kernel DagScheduler (semaphore parallelism)
5. Execute SQL (if verification passes)
6. Run Reflection for auto-repair (Phase 2.1)
7. Run Advanced Analytics (Phase 4)
8. Build final AgentResult with confidence + trace
9. Apply Critic assessment (Phase 2.2)
10. Run Learning pipeline (Phase 3)
11. Confidence circuit breaker → V1 fallback on low quality

The Supervisor itself contains NO business logic — it only coordinates.
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
from agents.registry import AgentRegistry


AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}


class _V2BridgeRegistry(AgentRegistry):
    """Bridge V2 AGENT_REGISTRY (str → class) to kernel AgentRegistry interface.

    Each get_agent() call instantiates a fresh agent instance so that
    parallel DAG nodes never share mutable state.
    """
    def get_agent(self, agent_type: str):
        key = (agent_type or "").lower()
        cls = AGENT_REGISTRY.get(key)
        if cls is None:
            raise KeyError(f"agent not found: {agent_type}")
        return cls()


AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}


def _lazy_register() -> None:
    """Lazily import and register all sub-agent classes."""
    if AGENT_REGISTRY:
        return

    from agents.data_agent_v2.knowledge_retriever import KnowledgeRetrieverAgent
    from agents.data_agent_v2.intent_agent import IntentAgent
    from agents.data_agent_v2.entity_agent import EntityAgent
    from agents.data_agent_v2.metric_agent import MetricAgent
    from agents.data_agent_v2.time_reasoning_agent import TimeReasoningAgent
    from agents.data_agent_v2.join_agent import JoinAgent
    from agents.data_agent_v2.semantic_agent import SemanticAgent
    from agents.data_agent_v2.planner_agent import PlannerAgent
    from agents.data_agent_v2.sql_compiler_agent import SQLCompilerAgent
    from agents.data_agent_v2.verification_agent import VerificationAgent

    AGENT_REGISTRY.update({
        "data_knowledge": KnowledgeRetrieverAgent,
        "data_intent": IntentAgent,
        "data_entity": EntityAgent,
        "data_metric": MetricAgent,
        "data_time": TimeReasoningAgent,
        "data_join": JoinAgent,
        "data_semantic": SemanticAgent,
        "data_planner": PlannerAgent,
        "data_compiler": SQLCompilerAgent,
        "data_verification": VerificationAgent,
    })


class DataAgentV2Supervisor:
    """Lightweight coordinator for the DataAgent V2 cognitive pipeline."""

    def __init__(self) -> None:
        _lazy_register()
        self._max_retries = 2

    async def execute(self, task: TaskMessage) -> AgentResult:
        from infra.config.settings import settings
        self._max_retries = int(getattr(settings, "data_agent_v2_supervisor_max_retries", 2))

        t0 = time.monotonic()
        self._trace_id = str(uuid.uuid4())

        # 1. Initialize cognitive context
        ctx = self._init_context(task)

        # 2. Load data source metadata
        await self._load_datasource_metadata(task, ctx)

        # 3. Knowledge Layer
        knowledge_enabled = bool(getattr(settings, "data_agent_v2_knowledge_retriever_enabled", True))
        if knowledge_enabled:
            t_kb = time.monotonic()
            ctx = await self._run_knowledge_layer(task, ctx)
            await self._record_event(self._trace_id, task, "knowledge_layer",
                                     {"duration_ms": int((time.monotonic() - t_kb) * 1000)},
                                     status="success")

        # 4. Check for direct SQL / pattern hits (fast path: skip reasoning DAG)
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
            # 5. Build and execute cognitive DAG
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

            # 5b. Expand DAG with skill templates if matched (Phase 4.4)
            skill_exec_enabled = enabled_agents.get("skill_execution", False)
            if skill_exec_enabled and ctx.matched_skills:
                dag = self._expand_skills(dag, ctx)

            t_dag = time.monotonic()
            ctx = await self._execute_dag(task, ctx, dag)
            await self._record_event(self._trace_id, task, "dag_execute",
                                     {"nodes": len(dag.nodes), "duration_ms": int((time.monotonic() - t_dag) * 1000)},
                                     status="success")

        # 5c. Clarification Gate: detect vague queries before SQL execution.
        # Skip if the user is already responding to a previous clarification
        # (clarify_context is non-empty) — in that case, proceed with the query.
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

        # 6. Execute SQL if verification passed
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

        # 7. Reflection: observe results, diagnose, repair (Phase 2.1)
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

        # 7b. Advanced analytics (Phase 4)
        if result_ctx.execution_rows and not result_ctx.execution_error:
            result_ctx = await self._run_advanced_analytics(task, result_ctx)

        # 8. Build final result
        result = self._build_final_result(task, result_ctx, t0)

        # 8b. Confidence circuit breaker: if V2 result quality is too low,
        # signal DataAgent wrapper to fall back to V1 pipeline.
        threshold = float(getattr(settings, "data_agent_v2_confidence_threshold", 0.40))
        if result.confidence < threshold and bool(getattr(settings, "data_agent_v2_fallback_to_v1", False)):
            await self._record_event(self._trace_id, task, "circuit_breaker",
                                     {"confidence": result.confidence, "threshold": threshold},
                                     status="error")
            raise LowConfidenceError(
                confidence=result.confidence,
                threshold=threshold,
                detail=f"sql={bool(result_ctx.compiled_sql)} rows={result_ctx.execution_row_count} err={result_ctx.execution_error or ''}",
            )

        # 9. Critic assessment: explainable confidence (Phase 2.2)
        critic_enabled = bool(getattr(settings, "data_agent_v2_critic_enabled", True))
        if critic_enabled:
            result = self._apply_critic(task, result, result_ctx)

        # 10. Learning: pattern extraction + knowledge update (Phase 3)
        learning_enabled = bool(getattr(settings, "data_agent_v2_learning_enabled", False))
        if learning_enabled:
            result_ctx = await self._run_learning_pipeline(task, result, result_ctx)

        await self._record_event(self._trace_id, task, "complete",
                                 {"total_ms": int((time.monotonic() - t0) * 1000),
                                  "confidence": result.confidence,
                                  "status": result.status},
                                 status=result.status)
        return result

    # ── Step Execution ────────────────────────────────────────────────

    async def _run_knowledge_layer(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """Execute KnowledgeRetrieverAgent."""
        own_session = None
        try:
            if not task.params.get("_db_session"):
                from infra.storage.database import AsyncSessionLocal
                own_session = AsyncSessionLocal()

            agent_cls = AGENT_REGISTRY["data_knowledge"]
            agent = agent_cls()
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
        """Execute the cognitive DAG while carrying merged CognitiveContext.

        The generic DagScheduler only forwards static node params. DataAgent V2
        needs each dependency wave to receive the latest cognitive state, so the
        supervisor keeps the same DAG topology but injects and merges context
        between waves.
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

    async def _run_dag_node(
        self,
        task: TaskMessage,
        node: DagNodeSpec,
        ctx: CognitiveContext,
        timeout_sec: int,
    ) -> AgentResult:
        """Run one V2 DAG node with the current cognitive context."""
        cls = AGENT_REGISTRY.get(node.agent_type)
        if cls is None:
            raise KeyError(f"agent not found: {node.agent_type}")

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
        result = await asyncio.wait_for(cls().execute(msg), timeout=timeout_sec)
        return self._coerce_agent_result(result)

    async def _execute_sql(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """Execute compiled SQL if verification passes."""
        if not ctx.compiled_sql:
            ctx.execution_error = "no compiled SQL generated by DataAgent V2"
            return ctx

        report = ctx.verification_report or {}
        if report.get("status") == "fail":
            ctx.execution_error = "SQL verification failed"
            return ctx

        try:
            dsn = task.params.get("_dsn", "")
            if not dsn:
                ctx.execution_error = "data source connection is not available"
                return ctx

            from execution.data.sql_executor import SQLExecutor
            from kernel.data_cognition.sql_validator import SQLValidator

            safe_sql = SQLValidator(default_limit=100).validate(ctx.compiled_sql)
            rows = await SQLExecutor().run_on_dsn(dsn, safe_sql)

            ctx.execution_rows = rows
            ctx.execution_row_count = len(rows)
            ctx.compiled_sql = safe_sql
            ctx.reflection_rounds = 0  # Will be set by ReflectionAgent if needed

        except Exception as exc:
            ctx.execution_error = str(exc)

        return ctx

    # ── Helpers ────────────────────────────────────────────────────────

    async def _run_reflection(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """Run ReflectionAgent to observe results and attempt repairs."""
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
        """Apply DataCriticAdapter for explainable confidence and quality assessment."""
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

    # ── Advanced Analytics (Phase 4) ────────────────────────────────────

    def _expand_skills(self, dag: DagPlanSpec, ctx: CognitiveContext) -> DagPlanSpec:
        """Expand DAG with analytical skill templates."""
        try:
            from agents.data_agent_v2.skills_engine import SkillsEngine

            engine = SkillsEngine()
            # Use the first matched skill
            skill = ctx.matched_skills[0]
            return engine.expand(skill, dag, ctx)
        except Exception as exc:
            logger.warning("Supervisor operation failed", error=str(exc))
            return dag

    async def _run_advanced_analytics(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> CognitiveContext:
        """Run advanced analytics agents on query results.

        Mode (controlled by data_agent_v2_advanced_analytics_mode):
        - "off": skip all advanced analytics
        - "manual": use individual feature flags (backward-compatible)
        - "auto": determine which agents to run based on intent and query keywords
        """
        from infra.config.settings import settings

        mode = str(getattr(settings, "data_agent_v2_advanced_analytics_mode", "manual") or "manual")

        if mode == "off":
            return ctx

        if mode == "auto":
            statistical_enabled, insight_enabled, viz_enabled = self._resolve_auto_analytics(ctx)
        else:
            # "manual" mode — use individual flags
            statistical_enabled = bool(getattr(settings, "data_agent_v2_statistical_enabled", False))
            insight_enabled = bool(getattr(settings, "data_agent_v2_insight_enabled", False))
            viz_enabled = bool(getattr(settings, "data_agent_v2_visualization_enabled", False))

        # Statistical analysis (Phase 4.1)
        if statistical_enabled:
            ctx = await self._run_agent(
                task, ctx, "data_statistical",
                "agents.data_agent_v2.statistical_agent", "StatisticalAgent",
            )

        # Insight generation (Phase 4.2)
        if insight_enabled:
            ctx = await self._run_agent(
                task, ctx, "data_insight",
                "agents.data_agent_v2.insight_agent", "InsightAgent",
            )

        # Visualization recommendation (Phase 4.3)
        if viz_enabled:
            ctx = await self._run_agent(
                task, ctx, "data_visualization",
                "agents.data_agent_v2.visualization_agent", "VisualizationAgent",
            )

        return ctx

    def _resolve_auto_analytics(self, ctx: CognitiveContext) -> tuple[bool, bool, bool]:
        """Determine which advanced analytics to run based on intent and query.

        Returns (statistical_enabled, insight_enabled, visualization_enabled).
        """
        query_lower = (ctx.query or "").lower()
        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""

        # Intent types that benefit from statistical analysis and insights
        analytical_intents = {
            "trend", "comparison", "anomaly_detection",
            "ranking", "composition", "distribution",
            "aggregation",  # COUNT/SUM by group also benefits from stats & insights
        }

        # Keywords that signal need for trend/statistical analysis
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
        """Run a single agent by module path and class name."""
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

    # ── Learning Layer (Phase 3) ────────────────────────────────────────

    async def _run_learning_pipeline(
        self, task: TaskMessage, result: AgentResult, ctx: CognitiveContext
    ) -> CognitiveContext:
        """Run learning pipeline: feedback collection → pattern extraction → knowledge update."""
        from infra.config.settings import settings

        # Ensure db session is available for learning agents
        _own_session = None
        if not task.params.get("_db_session"):
            try:
                from infra.storage.database import AsyncSessionLocal
                _own_session = AsyncSessionLocal()
                task.params["_db_session"] = _own_session
            except Exception as exc:
                logger.warning("Supervisor operation failed", error=str(exc))

        try:
            # 10a. Collect feedback if provided in task params
            feedback = task.params.get("feedback")
            if feedback:
                ctx = await self._run_feedback_collector(task, ctx, feedback)

            # 10b. Extract pattern from successful queries
            pattern_enabled = bool(getattr(settings, "data_agent_v2_pattern_memory_enabled", False))
            if pattern_enabled and result.status == "success" and ctx.compiled_sql:
                ctx = await self._run_pattern_extractor(task, ctx, result)

            # 10c. Apply knowledge updates if learning signals exist
            if ctx.learning_signals:
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
        """Run FeedbackCollectorAgent to classify and store user feedback."""
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
        """Run PatternExtractorAgent to store successful query patterns."""
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
        """Run KnowledgeUpdaterAgent to apply learning to knowledge assets."""
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

    # ── Event Recording (Phase P2: cognitive audit trail) ──────────────

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
        """Fire-and-forget cognitive event recording.

        Only writes when DATA_AGENT_V2_COGNITIVE_EVENTS_ENABLED=true.
        Failures are silently ignored — audit events must not block the pipeline.
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

    # ── Context Initialization ─────────────────────────────────────────

    def _init_context(self, task: TaskMessage) -> CognitiveContext:
        """Initialize a fresh CognitiveContext from TaskMessage.

        If clarify_context is provided (multi-turn follow-up), merge it
        with the original query so downstream agents see the full context.
        """
        query = task.query
        clarify_context = str(task.params.get("clarify_context", "") or "").strip()
        if clarify_context:
            query = f"原始问题：{query}\n用户补充信息：{clarify_context}"

        return CognitiveContext(
            query=query,
            data_source_id=task.params.get("data_source_id", ""),
            dialect=task.params.get("dialect", "postgresql"),
            schema_hint=task.params.get("schema_hint", ""),
            table_names=task.params.get("table_names", []),
            table_columns=task.params.get("table_columns", {}),
            semantic_config=task.params.get("semantic_config", {}),
            compiled_sql=str(task.params.get("sql", "") or "").strip() or None,
            clarify_context=clarify_context,
        )

    async def _load_datasource_metadata(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> None:
        """Load data source metadata if not already provided."""
        if ctx.table_names and ctx.table_columns and not ctx.data_source_id:
            return

        if not ctx.data_source_id:
            return

        try:
            from execution.data.db_router import DBConnectionInfo, DBRouter
            from gateway.api_gateway.routers.databases import _dec
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
                    task.params["_dsn"] = DBRouter().build_dsn(
                        DBConnectionInfo(
                            source_type=ds.source_type,
                            host=ds.host,
                            port=ds.port,
                            database=ds.database,
                            username=ds.username,
                            password=_dec(ds.password_encrypted),
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
        """Merge a sub-agent context without erasing prior agent outputs."""
        merged = base.to_dict()
        for key, value in update.to_dict().items():
            if value is None:
                continue
            if isinstance(value, (list, dict, str)) and not value:
                continue
            merged[key] = value
        return CognitiveContext.from_dict(merged)

    def _coerce_agent_result(self, result: AgentResult | dict[str, Any]) -> AgentResult:
        """Normalize sub-agent results to AgentResult at the supervisor boundary."""
        if isinstance(result, AgentResult):
            return result
        if isinstance(result, dict):
            return AgentResult(**result)
        raise TypeError(f"unsupported agent result type: {type(result).__name__}")

    def _build_result_refs(
        self, task: TaskMessage, ctx: CognitiveContext, rows: list[dict], sql: str
    ) -> list[dict[str, Any]]:
        """Build result references compatible with the orchestrator/UI."""
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
        """Build the final AgentResult from CognitiveContext."""
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        sql = ctx.compiled_sql or ""
        rows = ctx.execution_rows or []
        error = ctx.execution_error
        result_refs = self._build_result_refs(task, ctx, rows, sql)

        if error:
            return AgentResult(
                task_id=task.task_id,
                agent_type="data",
                status="error",
                content=f"数据查询执行失败：{error}",
                confidence=0.0,
                error=error,
                metadata={
                    "sql": sql,
                    "rows": rows[:20],
                    "row_count": len(rows),
                    "data_source_id": ctx.data_source_id,
                    "mode": "data_agent_v2",
                    "verification_report": ctx.verification_report,
                    "result_refs": result_refs,
                },
                agent_trace={
                    "elapsed_ms": elapsed_ms,
                    "pipeline": "data_agent_v2",
                    "error": error,
                },
            )

        # Build explanation (includes advanced analytics if available)
        content = self._format_rows_content(rows, sql, ctx)

        # Compute confidence (includes analytics bonuses)
        confidence = self._compute_confidence(ctx, rows, sql)

        # Collect evidence from advanced analytics
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

        return AgentResult(
            task_id=task.task_id,
            agent_type="data",
            status="success",
            content=content,
            confidence=confidence,
            metadata={
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
            },
            evidence=evidence,
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
        """Compute overall confidence from all pipeline signals."""
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
        # Advanced analytics bonuses
        if ctx.statistical_report:
            confidence += 0.03
        if ctx.insights:
            ic = ctx.insights.get("confidence", 0)
            if isinstance(ic, (int, float)) and ic > 0.7:
                confidence += 0.03
        if ctx.visualization_config:
            confidence += 0.02

        # Penalty for verification warnings
        if ctx.verification_report:
            issues = ctx.verification_report.get("issues", [])
            confidence -= 0.02 * len([i for i in issues if i.get("severity") in ("high", "critical")])

        return max(0.1, min(0.99, confidence))

    def _format_rows_content(
        self, rows: list[dict], sql: str, ctx: CognitiveContext | None = None
    ) -> str:
        """Format query results into human-readable content with analytics."""
        if not rows:
            return "查询未返回数据。"

        query_text = ctx.query if ctx else ""
        parts = [f"查询「{query_text}」返回 {len(rows)} 行数据。"]

        if sql:
            parts.append(f"执行SQL：\n```sql\n{sql}\n```")

        # Append insights if available
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

        # Append statistical summary if available (without insight summary)
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

        # Fallback when no advanced analytics are available
        if ctx and not has_insight_summary and not ctx.statistical_report:
            parts.append(self._build_fallback_description(ctx, rows))

        return "\n\n".join(parts)

    def _build_fallback_description(
        self, ctx: CognitiveContext, rows: list[dict]
    ) -> str:
        """Build a useful description when advanced analytics are unavailable."""
        fallback_parts = []

        intent = ctx.intent or {}
        intent_type = intent.get("intent_type", "") if isinstance(intent, dict) else ""

        # Map intent types to Chinese descriptions
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

        # Check if the query asks for trend/cause analysis that we can't fulfill
        query_lower = (ctx.query or "").lower()
        needs_trend = any(kw in query_lower for kw in ["趋势", "走势", "变化", "环比", "同比"])
        needs_cause = any(kw in query_lower for kw in ["原因", "为什么", "影响因素", "分析"])

        if needs_trend:
            # Check if schema has time columns
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
        """Detect likely time columns from schema and query context."""
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

    # ── Clarification Gate ──────────────────────────────────────────────

    async def _check_clarification(
        self, task: TaskMessage, ctx: CognitiveContext
    ) -> dict[str, Any] | None:
        """Check if the query is too vague and needs a clarification question.

        Returns a ClarificationQuestion dict if clarification is needed,
        or None if the query is clear enough to proceed.
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
        """Build an AgentResult carrying a clarification question.

        This short-circuits the normal pipeline — no SQL is executed.
        The frontend renders a clarification card instead of a result table.
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

        return AgentResult(
            task_id=task.task_id,
            agent_type="data",
            status="success",
            content=content,
            confidence=0.15,
            metadata={
                "rows": [],
                "row_count": 0,
                "sql": "",
                "data_source_id": ctx.data_source_id,
                "mode": "data_agent_v2",
                "needs_clarification": True,
                "clarification": clarification,
                "intent": ctx.intent,
                "result_refs": [],
            },
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
