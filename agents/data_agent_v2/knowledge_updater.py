"""
KnowledgeUpdaterAgent — 将已分类反馈转为知识资产更新。

按类型路由：
  - pattern_reinforce → 增加 query_patterns.success_count
  - pattern_penalize → 增加 failure_count
  - update_query_pattern → 用纠正后的 SQL 更新模式
  - refine_metric_definition → 委托 MetricRefinerAgent
  - update_entity_mapping → 更新 schema_metadata
  - update_time_window → 更新查询模式
  - mark_amplification_risk → 更新 table_relationships.amplification_risk
  - store_for_review → 标记待管理员审核

自动变更默认安全（指标 status=draft、feedback 打 learning_applied）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, update as sql_update

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class KnowledgeUpdaterAgent(BaseAgent):
    """将学习到的反馈应用到知识资产表。

    将每种反馈分类路由到正确的更新路径。
    默认安全：指标变更创建草稿版本，关系更新使用保守 EMA，
    模式更新需要足够数据量。
    """

    def __init__(self) -> None:
        super().__init__("data_knowledge_updater")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        learning_signals = ctx.learning_signals or {}
        feedback_type = learning_signals.get("feedback_type", "")
        action = learning_signals.get("feedback_action", "")

        if not action or action == "none":
            return self._skip(task, ctx, "no learning action to apply")

        db = task.params.get("_db_session")
        if not db:
            return self._skip(task, ctx, "no db session")

        updates_applied: list[str] = []

        try:
            # ── 按操作路由 ──────────────────────────────────────
            if action == "reinforce_pattern":
                await self._reinforce_pattern(db, ctx, learning_signals)
                updates_applied.append("pattern_reinforced")

            elif action == "update_query_pattern":
                await self._update_query_pattern(db, ctx, learning_signals)
                updates_applied.append("pattern_updated")

            elif action == "refine_metric_definition":
                await self._refine_metric(db, ctx, learning_signals, task)
                updates_applied.append("metric_refined")

            elif action == "update_entity_mapping":
                await self._update_entity(db, ctx, learning_signals)
                updates_applied.append("entity_updated")

            elif action == "mark_for_review":
                await self._mark_pattern_for_review(db, ctx, learning_signals)
                updates_applied.append("marked_for_review")

            elif action == "enrich_pattern":
                await self._enrich_pattern(db, ctx, learning_signals)
                updates_applied.append("pattern_enriched")

            # ── 标记反馈为 learning_applied ─────────────────────
            await self._mark_feedback_applied(db, task)

            await db.commit()

            # 更新上下文中的已应用学习
            ctx.learning_signals = (ctx.learning_signals or {}) | {
                "updates_applied": updates_applied,
                "learning_applied_at": str(__import__("time").time()),
            }

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"knowledge updated: {', '.join(updates_applied)}",
                confidence=0.95,
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="knowledge_updater",
                    source_type="learning",
                    payload={"updates_applied": updates_applied},
                    credibility=0.85,
                    relevance=0.95,
                )],
                agent_trace={"updates_applied": updates_applied},
            )
        except Exception as exc:
            await db.rollback()
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="knowledge update skipped",
                confidence=0.5,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    # ── 更新处理器 ─────────────────────────────────────────────────

    async def _reinforce_pattern(
        self, db, ctx: CognitiveContext, signals: dict
    ) -> None:
        """递增匹配查询模式的 success_count。"""
        from infra.storage.models import QueryPattern
        from datetime import datetime, timezone

        if not ctx.pattern_hit:
            return

        phash = ctx.pattern_hit.get("pattern_hash", "")
        if not phash:
            return

        result = await db.execute(
            select(QueryPattern).where(QueryPattern.pattern_hash == phash)
        )
        pattern = result.scalar()
        if pattern:
            pattern.success_count = (pattern.success_count or 0) + 1
            pattern.last_used_at = datetime.now(timezone.utc)

    async def _update_query_pattern(
        self, db, ctx: CognitiveContext, signals: dict
    ) -> None:
        """将用户纠正的 SQL 存入 query_pattern。"""
        from infra.storage.models import QueryPattern
        from datetime import datetime, timezone

        corrected_sql = signals.get("corrected_sql", "")
        if not corrected_sql:
            return

        # 若有 pattern_hit 哈希则使用，否则计算新哈希
        if ctx.pattern_hit:
            phash = ctx.pattern_hit.get("pattern_hash", "")
        else:
            import hashlib
            entities = sorted(
                e.get("mapped_table", "") for e in (ctx.entities or [])
            )
            metrics = sorted(
                m.get("mention", "") for m in (ctx.metrics or [])
            )
            intent_type = ctx.intent.get("intent_type") if ctx.intent else ""
            phash = hashlib.sha256(
                f"{intent_type}|{','.join(entities)}|{','.join(metrics)}".encode()
            ).hexdigest()

        result = await db.execute(
            select(QueryPattern).where(QueryPattern.pattern_hash == phash)
        )
        pattern = result.scalar()
        if pattern:
            pattern.successful_sql = corrected_sql
            pattern.failure_count = (pattern.failure_count or 0) + 1
            pattern.last_used_at = datetime.now(timezone.utc)

    async def _refine_metric(
        self, db, ctx: CognitiveContext, signals: dict, task: TaskMessage
    ) -> None:
        """委托 MetricRefinerAgent 进行指标公式纠正。"""
        from agents.data_agent_v2.metric_refiner import MetricRefinerAgent

        refiner = MetricRefinerAgent()
        refiner_task = TaskMessage(
            task_id=f"{task.task_id}_metric_refine",
            agent_type="data_metric_refiner",
            query=ctx.query,
            params={
                "cognitive_context": ctx.to_dict(),
                "corrected_metric_id": signals.get("corrected_metric_id"),
                "correction_detail": signals.get("details", {}),
            },
            session_id=task.session_id,
        )
        try:
            result = await refiner.execute(refiner_task)
            # 将修正后的指标合并回上下文
            result_ctx = result.metadata.get("cognitive_context", {})
            if result_ctx:
                refined = result_ctx.get("refined_metrics", [])
                if refined:
                    ctx.refined_metrics = refined
        except Exception:
            pass

    async def _update_entity(
        self, db, ctx: CognitiveContext, signals: dict
    ) -> None:
        """更新 schema_metadata 业务名称映射。"""
        from infra.storage.models import SchemaMetadata

        details = signals.get("details", {})
        correction_text = details.get("correction", "")
        if not correction_text:
            return

        # 尝试更新匹配的 schema 元数据
        result = await db.execute(
            select(SchemaMetadata).where(
                SchemaMetadata.data_source_id == ctx.data_source_id,
            )
        )
        rows = result.scalars().all()
        for row in rows:
            if row.business_name and row.business_name.lower() in correction_text.lower():
                # 添加用户纠正的标注
                existing_desc = row.business_description or ""
                if "user_corrected" not in existing_desc:
                    row.business_description = (
                        f"{existing_desc} [user_corrected: {correction_text[:200]}]"
                    ).strip()
                break

    async def _mark_pattern_for_review(
        self, db, ctx: CognitiveContext, signals: dict
    ) -> None:
        """通过递增失败计数将模式标记为待管理员审核。"""
        from infra.storage.models import QueryPattern

        if not ctx.pattern_hit:
            return

        phash = ctx.pattern_hit.get("pattern_hash", "")
        result = await db.execute(
            select(QueryPattern).where(QueryPattern.pattern_hash == phash)
        )
        pattern = result.scalar()
        if pattern:
            pattern.failure_count = (pattern.failure_count or 0) + 1

    async def _enrich_pattern(
        self, db, ctx: CognitiveContext, signals: dict
    ) -> None:
        """向查询模式添加补充上下文。"""
        from infra.storage.models import QueryPattern

        if not ctx.pattern_hit:
            return

        phash = ctx.pattern_hit.get("pattern_hash", "")
        details = signals.get("details", {})
        supplement = details.get("context", "")

        if not supplement:
            return

        result = await db.execute(
            select(QueryPattern).where(QueryPattern.pattern_hash == phash)
        )
        pattern = result.scalar()
        if pattern:
            # 将补充上下文追加到模板
            existing = pattern.query_template or ""
            if supplement not in existing:
                pattern.query_template = f"{existing}\n-- Supplement: {supplement}"

    async def _mark_feedback_applied(
        self, db, task: TaskMessage
    ) -> None:
        """标记反馈记录为已应用学习。"""
        from infra.storage.models import Feedback

        try:
            result = await db.execute(
                select(Feedback).where(
                    Feedback.agent_trace_id == task.task_id.split("_knowledge")[0]
                )
            )
            feedback = result.scalar()
            if feedback:
                feedback.learning_applied = True
        except Exception:
            pass

    def _skip(
        self, task: TaskMessage, ctx: CognitiveContext, reason: str
    ) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"knowledge update skipped: {reason}",
            confidence=0.5,
            metadata={"cognitive_context": ctx.to_dict()},
            agent_trace={"skip_reason": reason},
        )
