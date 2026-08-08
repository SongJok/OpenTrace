"""
KnowledgeRetrieverAgent — 查询知识资产表并向认知流水线注入已 grounding 的业务上下文。

连接知识层与推理层：拉取指标定义、schema 元数据、表关系、分析技能与查询模式，
写入 CognitiveContext，下游 Agent 无需猜测业务逻辑。
"""

from __future__ import annotations

import hashlib

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    CognitiveContext,
    KnowledgeRetrievalSpec,
    pack_cognitive_result,
    unpack_cognitive_context,
)


class KnowledgeRetrieverAgent(BaseAgent):
    """为给定分析查询检索相关知识资产。

    读取：metric_definitions、schema_metadata、table_relationships、
    analytical_skills、query_patterns。
    将结果注入 CognitiveContext。
    """

    def __init__(self) -> None:
        super().__init__("data_knowledge")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        db = task.params.get("_db_session")
        if db is None:
            return self._empty_result(task, ctx, "no db session provided")

        try:
            spec = KnowledgeRetrievalSpec(
                query=ctx.query,
                intent_type=ctx.intent.get("intent_type") if ctx.intent else None,
                entity_names=[e.get("mapped_table", "") for e in (ctx.entities or [])],
                metric_names=[m.get("mention", "") for m in (ctx.metrics or [])],
                data_source_id=ctx.data_source_id,
                table_names=ctx.table_names,
            )

            if ctx.data_source_id:
                await self._retrieve_metric_definitions(db, ctx, spec)
                await self._retrieve_table_semantics(db, ctx, spec)
                await self._retrieve_column_semantics(db, ctx, spec)
                await self._retrieve_table_relationships(db, ctx, spec)
                await self._retrieve_analytical_skills(db, ctx, spec)
                await self._check_query_patterns(db, ctx, spec)

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="knowledge retrieval complete",
                confidence=0.95,
                ctx=ctx,
                evidence=[
                    self._make_evidence(
                        source="knowledge_retriever",
                        source_type="system",
                        payload={
                            "matched_metrics": len(ctx.matched_metrics or []),
                            "matched_skills": len(ctx.matched_skills or []),
                            "matched_relationships": len(ctx.matched_relationships or []),
                            "table_semantics_count": len(ctx.table_semantics or []),
                            "column_semantics_count": len(ctx.column_semantics or []),
                            "pattern_hit": ctx.pattern_hit is not None,
                        },
                        credibility=0.90,
                        relevance=1.0,
                    )
                ],
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                confidence=0.0,
                error=str(exc),
                metadata={"cognitive_context": ctx.to_dict()},
            )

    # ── 检索方法 ──────────────────────────────────────────────────

    async def _retrieve_metric_definitions(
        self,
        db: AsyncSession,
        ctx: CognitiveContext,
        spec: KnowledgeRetrievalSpec,
    ) -> None:
        """按名称/别名和 data_source_id 匹配 metric_definitions。"""
        from infra.storage.models import MetricDefinition

        conditions = [MetricDefinition.data_source_id == spec.data_source_id]
        keyword_conditions: list = []

        for name in spec.metric_names:
            keyword_conditions.append(MetricDefinition.name.ilike(f"%{name}%"))
            # 同时检查别名（ARRAY 包含查询因方言而异，使用 OR）
            keyword_conditions.append(MetricDefinition.aliases.any(name))

        # 同时尝试从查询文本直接匹配
        query_words = spec.query.lower().split()
        for word in query_words:
            if len(word) >= 2:
                keyword_conditions.append(MetricDefinition.name.ilike(f"%{word}%"))

        if keyword_conditions:
            conditions.append(or_(*keyword_conditions))

        conditions.append(MetricDefinition.status == "published")

        result = await db.execute(select(MetricDefinition).where(and_(*conditions)).limit(10))
        rows = result.scalars().all()

        ctx.matched_metrics = [
            {
                "id": r.id,
                "name": r.name,
                "aliases": r.aliases,
                "formula": r.formula,
                "underlying_columns": r.underlying_columns,
                "agg_function": r.agg_function,
                "business_definition": r.business_definition,
                "unit": r.unit,
                "category": r.category,
                "tags": r.tags,
                "sensitivity": r.sensitivity,
            }
            for r in rows
        ]

    async def _retrieve_column_semantics(
        self,
        db: AsyncSession,
        ctx: CognitiveContext,
        spec: KnowledgeRetrievalSpec,
    ) -> None:
        """检索本查询涉及表的 schema_metadata。"""
        from infra.storage.models import SchemaMetadata

        if not spec.table_names:
            return

        result = await db.execute(
            select(SchemaMetadata).where(
                and_(
                    SchemaMetadata.data_source_id == spec.data_source_id,
                    SchemaMetadata.table_name.in_(spec.table_names),
                    SchemaMetadata.annotation_status != "rejected",
                )
            )
        )
        rows = result.scalars().all()

        ctx.column_semantics = [
            {
                "table_name": r.table_name,
                "column_name": r.column_name,
                "business_name": r.business_name,
                "business_description": r.business_description,
                "aliases": r.aliases or [],
                "tags": r.tags or [],
                "semantic_type": r.semantic_type,
                "value_map": r.value_map,
                "is_primary_key": r.is_primary_key,
                "is_foreign_key": r.is_foreign_key,
                "is_time_column": r.is_time_column,
                "time_grain": r.time_grain,
                "is_metric_column": r.is_metric_column,
                "is_dimension_column": r.is_dimension_column,
                "is_sensitive": r.is_sensitive,
                "lifecycle_stage": r.lifecycle_stage,
                "sample_values": r.sample_values,
                "annotation_source": r.annotation_source,
                "annotation_status": r.annotation_status,
                "annotation_confidence": r.annotation_confidence,
            }
            for r in rows
            if r.annotation_status == "verified"
            or (
                r.annotation_source == "database_comment"
                and float(r.annotation_confidence or 0) >= 0.85
            )
        ]

    async def _retrieve_table_semantics(
        self,
        db: AsyncSession,
        ctx: CognitiveContext,
        spec: KnowledgeRetrievalSpec,
    ) -> None:
        """读取人工审核或高可信数据库注释形成的表级语义。"""
        from infra.storage.models import SchemaTableMetadata

        if not spec.table_names:
            return
        rows = list(
            (
                await db.execute(
                    select(SchemaTableMetadata).where(
                        SchemaTableMetadata.data_source_id == spec.data_source_id,
                        SchemaTableMetadata.table_name.in_(spec.table_names),
                        SchemaTableMetadata.annotation_status != "rejected",
                    )
                )
            )
            .scalars()
            .all()
        )
        ctx.table_semantics = [
            {
                "table_name": row.table_name,
                "business_name": row.business_name,
                "business_description": row.business_description,
                "aliases": row.aliases or [],
                "tags": row.tags or [],
                "annotation_source": row.annotation_source,
                "annotation_status": row.annotation_status,
                "annotation_confidence": row.annotation_confidence,
            }
            for row in rows
            if row.annotation_status == "verified"
            or (
                row.annotation_source == "database_comment"
                and float(row.annotation_confidence or 0) >= 0.85
            )
        ]

    async def _retrieve_table_relationships(
        self,
        db: AsyncSession,
        ctx: CognitiveContext,
        spec: KnowledgeRetrievalSpec,
    ) -> None:
        """检索涉及表的已验证关系。"""
        from infra.storage.models import TableRelationship

        if len(spec.table_names) < 2:
            return

        result = await db.execute(
            select(TableRelationship)
            .where(
                and_(
                    TableRelationship.data_source_id == spec.data_source_id,
                    TableRelationship.left_table.in_(spec.table_names),
                    TableRelationship.right_table.in_(spec.table_names),
                )
            )
            .order_by(
                TableRelationship.is_verified.desc(),
                TableRelationship.success_rate.desc(),
                TableRelationship.usage_count.desc(),
            )
            .limit(20)
        )
        rows = result.scalars().all()

        ctx.matched_relationships = [
            {
                "left_table": r.left_table,
                "left_column": r.left_column,
                "right_table": r.right_table,
                "right_column": r.right_column,
                "join_type": r.join_type,
                "cardinality": r.cardinality,
                "amplification_risk": r.amplification_risk,
                "is_verified": r.is_verified,
                "usage_count": r.usage_count,
                "success_rate": r.success_rate,
            }
            for r in rows
        ]

    async def _retrieve_analytical_skills(
        self,
        db: AsyncSession,
        ctx: CognitiveContext,
        spec: KnowledgeRetrievalSpec,
    ) -> None:
        """按意图类型匹配 analytical_skills。"""
        from infra.storage.models import AnalyticalSkill

        conditions = [AnalyticalSkill.status == "active"]

        if spec.intent_type:
            conditions.append(AnalyticalSkill.required_intent_types.any(spec.intent_type))

        result = await db.execute(select(AnalyticalSkill).where(and_(*conditions)).limit(5))
        rows = result.scalars().all()

        ctx.matched_skills = [
            {
                "id": r.id,
                "name": r.name,
                "skill_type": r.skill_type,
                "description": r.description,
                "plan_template": r.plan_template,
                "sql_template": r.sql_template,
                "visualization_hint": r.visualization_hint,
                "parameters_schema": r.parameters_schema,
                "examples": r.examples,
            }
            for r in rows
        ]

    async def _check_query_patterns(
        self,
        db: AsyncSession,
        ctx: CognitiveContext,
        spec: KnowledgeRetrievalSpec,
    ) -> None:
        """检查是否有相似查询曾成功执行。"""
        from infra.storage.models import QueryPattern

        pattern_key = f"{spec.intent_type}|{','.join(sorted(spec.entity_names))}|{','.join(sorted(spec.metric_names))}"
        pattern_hash = hashlib.sha256(pattern_key.encode()).hexdigest()

        result = await db.execute(
            select(QueryPattern).where(QueryPattern.pattern_hash == pattern_hash).limit(1)
        )
        row = result.scalar()

        if row and row.successful_sql and row.success_count >= 2:
            ctx.pattern_hit = {
                "pattern_hash": row.pattern_hash,
                "successful_sql": row.successful_sql,
                "success_count": row.success_count,
                "avg_confidence": row.avg_confidence,
            }

    # ── 辅助方法 ──────────────────────────────────────────────────

    def _empty_result(
        self, task: TaskMessage, ctx: CognitiveContext, reason: str = ""
    ) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content="knowledge retrieval skipped",
            confidence=0.5,
            metadata={"cognitive_context": ctx.to_dict()},
            agent_trace={"warning": reason},
        )
