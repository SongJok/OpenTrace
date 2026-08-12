"""从授权数据目录中选择最可信的数据源。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from data_agent.contracts import DataSourceDecision
from data_agent.source_resolution import SourceCatalogEntry, SourceSignal, TrustedSourceSelector
from infra.config.settings import settings
from infra.security.resource_scope import accessible_data_sources_statement
from infra.storage.data_agent_models import (
    DataAgentLearningPattern,
    DataAgentProfile,
    DataAgentSemanticAsset,
)
from infra.storage.models import (
    DataSource,
    DataSourceSchema,
    MetricDefinition,
    SchemaMetadata,
    SchemaTableMetadata,
)
from infra.storage.sql_asset_models import SQLAsset


def _text(*values) -> str:
    return " ".join(
        (
            json.dumps(value, ensure_ascii=False, default=str)
            if isinstance(value, dict | list)
            else str(value or "")
        )
        for value in values
    )


class OpenTraceSourceResolver:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.selector = TrustedSourceSelector(
            minimum_score=settings.data_agent_source_min_score,
            ambiguity_delta=settings.data_agent_source_ambiguity_delta,
        )

    async def resolve(
        self,
        *,
        question: str,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
        explicit_id: str | None = None,
        candidate_ids: list[str] | None = None,
    ) -> DataSourceDecision:
        statement = accessible_data_sources_statement(
            user_id=user_id,
            tenant_metadata={"tenant_id": tenant_id, "workspace_id": workspace_id},
            required_permission="query",
            active_only=True,
        )
        candidate_restricted = bool(candidate_ids)
        allowed_ids: set[str] | None = (
            {str(item) for item in candidate_ids or [] if str(item)}
            if candidate_restricted
            else None
        )
        if allowed_ids is not None:
            if not allowed_ids:
                return self.selector.select(question, [], explicit_id=explicit_id)
            statement = statement.where(DataSource.id.in_(sorted(allowed_ids)))
        sources = list((await self.db.execute(statement.order_by(DataSource.name))).scalars().all())
        entries = {
            source.id: SourceCatalogEntry(
                data_source_id=source.id,
                name=source.name,
                source_type=source.source_type,
                signals=[
                    SourceSignal(
                        kind="source_name",
                        source_id=f"data-source:{source.id}",
                        text=_text(source.name, source.database, source.source_type),
                    )
                ],
            )
            for source in sources
        }
        if not entries:
            return self.selector.select(question, [], explicit_id=explicit_id)
        source_ids = list(entries)
        await self._add_schema_signals(entries, source_ids)
        await self._add_metric_signals(entries, source_ids)
        await self._add_semantic_signals(entries, source_ids, tenant_id, workspace_id)
        await self._add_sql_signals(entries, source_ids, tenant_id, workspace_id)
        await self._add_execution_signals(
            entries,
            source_ids,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        await self._add_profile_flags(
            entries,
            source_ids,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        decision = self.selector.select(question, list(entries.values()), explicit_id=explicit_id)
        if (
            not settings.data_agent_source_resolution_enabled
            and not explicit_id
            and len(entries) > 1
            and decision.status == "selected"
        ):
            return decision.model_copy(
                update={
                    "status": "needs_clarification",
                    "selected_data_source_id": None,
                    "selected_data_source_name": None,
                    "reason": "可信数据源自动选择已关闭，请显式选择数据源",
                }
            )
        return decision

    async def _add_schema_signals(
        self, entries: dict[str, SourceCatalogEntry], source_ids: list[str]
    ) -> None:
        synced = set(
            (
                await self.db.execute(
                    select(DataSourceSchema.data_source_id).where(
                        DataSourceSchema.data_source_id.in_(source_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for source_id in synced:
            entries[source_id].schema_synced = True
        tables = list(
            (
                await self.db.execute(
                    select(SchemaTableMetadata)
                    .where(
                        SchemaTableMetadata.data_source_id.in_(source_ids),
                        SchemaTableMetadata.annotation_status == "verified",
                    )
                    .limit(5000)
                )
            )
            .scalars()
            .all()
        )
        columns = list(
            (
                await self.db.execute(
                    select(SchemaMetadata)
                    .where(
                        SchemaMetadata.data_source_id.in_(source_ids),
                        SchemaMetadata.annotation_status == "verified",
                    )
                    .limit(10000)
                )
            )
            .scalars()
            .all()
        )
        for table in tables:
            entries[table.data_source_id].signals.append(
                SourceSignal(
                    kind="schema",
                    source_id=f"schema-table:{table.id}",
                    text=_text(
                        table.table_name,
                        table.business_name,
                        table.business_description,
                        table.aliases,
                        table.tags,
                    ),
                    certified=True,
                )
            )
        for column in columns:
            entries[column.data_source_id].signals.append(
                SourceSignal(
                    kind="schema",
                    source_id=f"schema-column:{column.id}",
                    text=_text(
                        column.table_name,
                        column.column_name,
                        column.business_name,
                        column.business_description,
                        column.aliases,
                        column.semantic_type,
                    ),
                    certified=True,
                )
            )

    async def _add_metric_signals(
        self, entries: dict[str, SourceCatalogEntry], source_ids: list[str]
    ) -> None:
        metrics = list(
            (
                await self.db.execute(
                    select(MetricDefinition)
                    .where(
                        MetricDefinition.data_source_id.in_(source_ids),
                        MetricDefinition.status == "published",
                    )
                    .limit(5000)
                )
            )
            .scalars()
            .all()
        )
        for metric in metrics:
            certified = bool(
                metric.certification_level == "certified"
                and metric.approved_by
                and metric.owner
                and metric.evidence_refs
            )
            entries[metric.data_source_id].signals.append(
                SourceSignal(
                    kind="metric",
                    source_id=f"metric:{metric.id}",
                    text=_text(
                        metric.name,
                        metric.aliases,
                        metric.business_definition,
                        metric.business_domain,
                        metric.tags,
                        metric.owner,
                    ),
                    certified=certified,
                )
            )

    async def _add_semantic_signals(
        self,
        entries: dict[str, SourceCatalogEntry],
        source_ids: list[str],
        tenant_id: str,
        workspace_id: str,
    ) -> None:
        statement = select(DataAgentSemanticAsset).where(
            DataAgentSemanticAsset.tenant_id == tenant_id,
            DataAgentSemanticAsset.workspace_id == workspace_id,
            DataAgentSemanticAsset.data_source_id.in_(source_ids),
            DataAgentSemanticAsset.status == "published",
        )
        rows = list((await self.db.execute(statement.limit(5000))).scalars().all())
        now = datetime.now(UTC)
        for row in rows:
            if row.valid_from and now < self._utc(row.valid_from):
                continue
            if row.valid_to and now >= self._utc(row.valid_to):
                continue
            kind = row.asset_type if row.asset_type in {"report", "lineage"} else "semantic"
            payload = dict(row.definition_json or {})
            blocked = row.asset_type == "source_policy" and bool(
                payload.get("blocked")
                or payload.get("deny_sql_generation")
                or payload.get("deny_execution")
            )
            entries[row.data_source_id].signals.append(
                SourceSignal(
                    kind=kind,
                    source_id=f"semantic-asset:{row.id}",
                    text=_text(
                        row.title,
                        row.description,
                        row.business_domain,
                        row.owner,
                        payload,
                    ),
                    certified=row.authority == "governed",
                    blocked=blocked,
                )
            )

    async def _add_sql_signals(
        self,
        entries: dict[str, SourceCatalogEntry],
        source_ids: list[str],
        tenant_id: str,
        workspace_id: str,
    ) -> None:
        statement = select(SQLAsset).where(
            SQLAsset.tenant_id == tenant_id,
            SQLAsset.workspace_id == workspace_id,
            SQLAsset.data_source_id.in_(source_ids),
            SQLAsset.status == "published",
            SQLAsset.corpus_role == "retrieval",
            SQLAsset.quality_status == "verified",
            SQLAsset.executable.is_(True),
        )
        rows = list((await self.db.execute(statement.limit(5000))).scalars().all())
        for row in rows:
            entries[row.data_source_id].signals.append(
                SourceSignal(
                    kind="sql_asset",
                    source_id=f"sql-asset:{row.id}",
                    text=_text(
                        row.title,
                        row.description,
                        row.domain,
                        row.tags,
                        row.knowledge_metadata,
                        row.tables,
                        row.columns,
                    ),
                    certified=True,
                )
            )

    async def _add_execution_signals(
        self,
        entries: dict[str, SourceCatalogEntry],
        source_ids: list[str],
        *,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> None:
        patterns = list(
            (
                await self.db.execute(
                    select(DataAgentLearningPattern)
                    .where(
                        DataAgentLearningPattern.user_id == user_id,
                        DataAgentLearningPattern.tenant_id == tenant_id,
                        DataAgentLearningPattern.workspace_id == workspace_id,
                        DataAgentLearningPattern.data_source_id.in_(source_ids),
                        DataAgentLearningPattern.scope_key == "__global__",
                        DataAgentLearningPattern.status == "trusted",
                    )
                    .order_by(DataAgentLearningPattern.last_verified_at.desc())
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )
        for row in patterns:
            entries[row.data_source_id].signals.append(
                SourceSignal(
                    kind="execution_memory",
                    source_id=f"learning-pattern:{row.id}",
                    text=_text(row.question_examples, row.logical_plan_json),
                    certified=True,
                )
            )

    async def _add_profile_flags(
        self,
        entries: dict[str, SourceCatalogEntry],
        source_ids: list[str],
        *,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> None:
        rows = set(
            (
                await self.db.execute(
                    select(DataAgentProfile.data_source_id).where(
                        DataAgentProfile.user_id == user_id,
                        DataAgentProfile.tenant_id == tenant_id,
                        DataAgentProfile.workspace_id == workspace_id,
                        DataAgentProfile.data_source_id.in_(source_ids),
                        DataAgentProfile.status == "current",
                        or_(
                            DataAgentProfile.expires_at.is_(None),
                            DataAgentProfile.expires_at > datetime.now(UTC),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for source_id in rows:
            entries[source_id].profile_current = True

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
