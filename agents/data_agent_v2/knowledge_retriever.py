"""
KnowledgeRetrieverAgent — queries knowledge asset tables and injects
grounded business context into the cognitive pipeline.

This agent bridges the Knowledge Layer and Reasoning Layer: it retrieves
metric definitions, schema metadata, table relationships, analytical skills,
and query patterns, then attaches them to CognitiveContext so downstream
agents never need to guess business logic.
"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    CognitiveContext,
    KnowledgeRetrievalSpec,
    pack_cognitive_result,
    unpack_cognitive_context,
)


class KnowledgeRetrieverAgent(BaseAgent):
    """Retrieve relevant knowledge assets for a given analytical query.

    Reads from: metric_definitions, schema_metadata, table_relationships,
    analytical_skills, query_patterns.
    Injects results into CognitiveContext.
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
                evidence=[self._make_evidence(
                    source="knowledge_retriever",
                    source_type="system",
                    payload={
                        "matched_metrics": len(ctx.matched_metrics or []),
                        "matched_skills": len(ctx.matched_skills or []),
                        "matched_relationships": len(ctx.matched_relationships or []),
                        "column_semantics_count": len(ctx.column_semantics or []),
                        "pattern_hit": ctx.pattern_hit is not None,
                    },
                    credibility=0.90,
                    relevance=1.0,
                )],
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

    # ── Retrieval Methods ──────────────────────────────────────────────

    async def _retrieve_metric_definitions(
        self, db: AsyncSession, ctx: CognitiveContext, spec: KnowledgeRetrievalSpec,
    ) -> None:
        """Match metric_definitions by name/alias and data_source_id."""
        from infra.storage.models import MetricDefinition

        conditions = [MetricDefinition.data_source_id == spec.data_source_id]
        keyword_conditions: list = []

        for name in spec.metric_names:
            keyword_conditions.append(MetricDefinition.name.ilike(f"%{name}%"))
            # Also check aliases (ARRAY containment is dialect-specific, use OR)
            keyword_conditions.append(MetricDefinition.aliases.any(name))

        # Also try to match from query text directly
        query_words = spec.query.lower().split()
        for word in query_words:
            if len(word) >= 2:
                keyword_conditions.append(MetricDefinition.name.ilike(f"%{word}%"))

        if keyword_conditions:
            conditions.append(or_(*keyword_conditions))

        conditions.append(MetricDefinition.status == "published")

        result = await db.execute(
            select(MetricDefinition).where(and_(*conditions)).limit(10)
        )
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
        self, db: AsyncSession, ctx: CognitiveContext, spec: KnowledgeRetrievalSpec,
    ) -> None:
        """Retrieve schema_metadata for tables involved in this query."""
        from infra.storage.models import SchemaMetadata

        if not spec.table_names:
            return

        result = await db.execute(
            select(SchemaMetadata).where(
                and_(
                    SchemaMetadata.data_source_id == spec.data_source_id,
                    SchemaMetadata.table_name.in_(spec.table_names),
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
            }
            for r in rows
        ]

    async def _retrieve_table_relationships(
        self, db: AsyncSession, ctx: CognitiveContext, spec: KnowledgeRetrievalSpec,
    ) -> None:
        """Retrieve verified table relationships for the involved tables."""
        from infra.storage.models import TableRelationship

        if len(spec.table_names) < 2:
            return

        result = await db.execute(
            select(TableRelationship).where(
                and_(
                    TableRelationship.data_source_id == spec.data_source_id,
                    TableRelationship.left_table.in_(spec.table_names),
                    TableRelationship.right_table.in_(spec.table_names),
                )
            ).order_by(
                TableRelationship.is_verified.desc(),
                TableRelationship.success_rate.desc(),
                TableRelationship.usage_count.desc(),
            ).limit(20)
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
        self, db: AsyncSession, ctx: CognitiveContext, spec: KnowledgeRetrievalSpec,
    ) -> None:
        """Match analytical_skills by intent type."""
        from infra.storage.models import AnalyticalSkill

        conditions = [AnalyticalSkill.status == "active"]

        if spec.intent_type:
            conditions.append(
                AnalyticalSkill.required_intent_types.any(spec.intent_type)
            )

        result = await db.execute(
            select(AnalyticalSkill).where(and_(*conditions)).limit(5)
        )
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
        self, db: AsyncSession, ctx: CognitiveContext, spec: KnowledgeRetrievalSpec,
    ) -> None:
        """Check if a similar query has been executed successfully before."""
        from infra.storage.models import QueryPattern

        pattern_key = f"{spec.intent_type}|{','.join(sorted(spec.entity_names))}|{','.join(sorted(spec.metric_names))}"
        pattern_hash = hashlib.sha256(pattern_key.encode()).hexdigest()

        result = await db.execute(
            select(QueryPattern).where(
                QueryPattern.pattern_hash == pattern_hash
            ).limit(1)
        )
        row = result.scalar()

        if row and row.successful_sql and row.success_count >= 2:
            ctx.pattern_hit = {
                "pattern_hash": row.pattern_hash,
                "successful_sql": row.successful_sql,
                "success_count": row.success_count,
                "avg_confidence": row.avg_confidence,
            }

    # ── Helpers ────────────────────────────────────────────────────────

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
