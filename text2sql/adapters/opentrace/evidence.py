"""OpenTrace 数据目录、语义资产和知识库适配器。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.metadata.schema_inspector import load_schema_inspection
from infra.storage.models import (
    AnalyticalSkill,
    DataSource,
    KnowledgeClaim,
    MetricDefinition,
    SchemaMetadata,
    SchemaTableMetadata,
    TableRelationship,
)
from infra.storage.text2sql_models import Text2SQLSemanticAsset
from services.sql_assets import retrieve_sql_assets
from text2sql.contracts import (
    Authority,
    DataScope,
    EvidenceBundle,
    EvidenceItem,
    EvidenceType,
    ResearchPlan,
)


def _tokens(value: str) -> set[str]:
    result = set(re.findall(r"[a-zA-Z0-9_]+", str(value or "").lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", str(value or "")):
        result.add(segment)
        result.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return result


def _score(question_tokens: set[str], *values: Any) -> int:
    text = " ".join(
        (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, dict | list)
            else str(value or "")
        )
        for value in values
    ).lower()
    return sum(1 for token in question_tokens if token and token in text)


class OpenTraceEvidenceProvider:
    def __init__(self, db: AsyncSession, data_source: DataSource) -> None:
        self.db = db
        self.data_source = data_source

    async def collect(self, scope: DataScope, question: str, plan: ResearchPlan) -> EvidenceBundle:
        inspection = await load_schema_inspection(self.db, self.data_source.id)
        dialect = str(self.data_source.source_type or "mysql").lower()
        schema_fingerprint = hashlib.sha256(
            json.dumps(inspection.schema_payload or {}, sort_keys=True, ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
        items: list[EvidenceItem] = []
        for table, columns in inspection.column_map.items():
            items.append(
                EvidenceItem(
                    type=EvidenceType.SCHEMA,
                    source_id=f"schema:{self.data_source.id}:{table}",
                    source_name="DataSourceSchema",
                    authority=Authority.LIVE_SYSTEM,
                    confidence=1.0,
                    version=schema_fingerprint,
                    scope={"data_source_id": self.data_source.id},
                    payload={"table": table, "columns": columns},
                )
            )
        table_metadata = list(
            (
                await self.db.execute(
                    select(SchemaTableMetadata).where(
                        SchemaTableMetadata.data_source_id == self.data_source.id,
                        SchemaTableMetadata.annotation_status != "rejected",
                    )
                )
            )
            .scalars()
            .all()
        )
        for table_row in table_metadata:
            if (
                table_row.annotation_status != "verified"
                and table_row.annotation_source != "database_comment"
            ):
                continue
            items.append(
                EvidenceItem(
                    type=EvidenceType.ENTITY,
                    source_id=f"table-semantic:{table_row.id}",
                    source_name="SchemaTableMetadata",
                    authority=(
                        Authority.GOVERNED
                        if table_row.annotation_status == "verified"
                        else Authority.VERIFIED
                    ),
                    confidence=float(table_row.annotation_confidence or 0.5),
                    version=table_row.schema_fingerprint,
                    scope={"data_source_id": self.data_source.id},
                    payload={
                        "table": table_row.table_name,
                        "business_name": table_row.business_name,
                        "description": table_row.business_description,
                        "aliases": table_row.aliases or [],
                        "tags": table_row.tags or [],
                    },
                )
            )
        column_rows = list(
            (
                await self.db.execute(
                    select(SchemaMetadata).where(
                        SchemaMetadata.data_source_id == self.data_source.id,
                        SchemaMetadata.annotation_status != "rejected",
                    )
                )
            )
            .scalars()
            .all()
        )
        for column_row in column_rows:
            if (
                column_row.annotation_status != "verified"
                and column_row.annotation_source != "database_comment"
            ):
                continue
            items.append(
                EvidenceItem(
                    type=EvidenceType.COLUMN_PROFILE,
                    source_id=f"column-semantic:{column_row.id}",
                    source_name="SchemaMetadata",
                    authority=(
                        Authority.GOVERNED
                        if column_row.annotation_status == "verified"
                        else Authority.VERIFIED
                    ),
                    confidence=float(column_row.annotation_confidence or 0.5),
                    version=column_row.schema_fingerprint,
                    scope={"data_source_id": self.data_source.id},
                    sensitive=bool(column_row.is_sensitive),
                    payload={
                        "table": column_row.table_name,
                        "column": column_row.column_name,
                        "business_name": column_row.business_name,
                        "description": column_row.business_description,
                        "aliases": column_row.aliases or [],
                        "semantic_type": column_row.semantic_type,
                        "value_map": column_row.value_map or {},
                        "is_time": column_row.is_time_column,
                        "is_dimension": column_row.is_dimension_column,
                        "is_metric": column_row.is_metric_column,
                        "sensitive": column_row.is_sensitive,
                    },
                )
            )

        question_tokens = _tokens(question)
        metric_rows = list(
            (
                await self.db.execute(
                    select(MetricDefinition).where(
                        MetricDefinition.data_source_id == self.data_source.id,
                        MetricDefinition.status == "published",
                    )
                )
            )
            .scalars()
            .all()
        )
        metric_rows.sort(
            key=lambda metric_row: _score(
                question_tokens,
                metric_row.name,
                metric_row.aliases,
                metric_row.business_definition,
                metric_row.category,
                metric_row.tags,
            ),
            reverse=True,
        )
        for metric_row in metric_rows[:50]:
            items.append(
                EvidenceItem(
                    type=EvidenceType.METRIC,
                    source_id=f"metric:{metric_row.id}",
                    source_name="MetricDefinition",
                    authority=Authority.GOVERNED,
                    confidence=1.0,
                    version=str(metric_row.version),
                    scope={"data_source_id": self.data_source.id},
                    payload={
                        "name": metric_row.name,
                        "aliases": metric_row.aliases or [],
                        "formula": metric_row.formula,
                        "underlying_columns": metric_row.underlying_columns or [],
                        "aggregation": metric_row.agg_function,
                        "business_definition": metric_row.business_definition,
                        "unit": metric_row.unit,
                        "required_filters": (
                            (metric_row.business_definition or "")
                            .split(";固有过滤：", 1)[-1]
                            .split(";")
                            if "固有过滤：" in (metric_row.business_definition or "")
                            else []
                        ),
                    },
                )
            )

        relationships = list(
            (
                await self.db.execute(
                    select(TableRelationship)
                    .where(TableRelationship.data_source_id == self.data_source.id)
                    .order_by(
                        TableRelationship.is_verified.desc(), TableRelationship.success_rate.desc()
                    )
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        for relationship_row in relationships:
            items.append(
                EvidenceItem(
                    type=EvidenceType.RELATIONSHIP,
                    source_id=f"relationship:{relationship_row.id}",
                    source_name="TableRelationship",
                    authority=(
                        Authority.GOVERNED if relationship_row.is_verified else Authority.INFERRED
                    ),
                    confidence=float(relationship_row.success_rate or 0.5),
                    scope={"data_source_id": self.data_source.id},
                    payload={
                        "left_table": relationship_row.left_table,
                        "left_column": relationship_row.left_column,
                        "right_table": relationship_row.right_table,
                        "right_column": relationship_row.right_column,
                        "join_type": relationship_row.join_type,
                        "cardinality": relationship_row.cardinality,
                        "amplification_risk": relationship_row.amplification_risk,
                        "verified": relationship_row.is_verified,
                    },
                )
            )

        requested_types = {step.source for step in plan.steps}
        if EvidenceType.SQL_ASSET in requested_types:
            assets = await retrieve_sql_assets(
                self.db,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                data_source_id=self.data_source.id,
                question=question,
                dialect=dialect,
                project_id=scope.project_id,
                include_draft_reference=False,
                available_tables=list(inspection.column_map) or inspection.table_names,
            )
            for sql_asset in assets[:10]:
                items.append(
                    EvidenceItem(
                        type=EvidenceType.SQL_ASSET,
                        source_id=f"sql-asset:{sql_asset.id}",
                        source_name="SQLAsset",
                        authority=Authority.VERIFIED,
                        confidence=0.92,
                        version=sql_asset.schema_fingerprint,
                        scope={
                            "tenant_id": scope.tenant_id,
                            "workspace_id": scope.workspace_id,
                            "data_source_id": self.data_source.id,
                        },
                        payload={
                            "title": sql_asset.title,
                            "description": sql_asset.description,
                            "sql": sql_asset.normalized_sql,
                            "tables": sql_asset.tables or [],
                            "columns": sql_asset.columns or [],
                            "knowledge": sql_asset.knowledge_metadata or {},
                        },
                    )
                )

        if EvidenceType.SKILL in requested_types:
            skills = list(
                (
                    await self.db.execute(
                        select(AnalyticalSkill).where(AnalyticalSkill.status == "active").limit(30)
                    )
                )
                .scalars()
                .all()
            )
            for skill in skills:
                items.append(
                    EvidenceItem(
                        type=EvidenceType.SKILL,
                        source_id=f"skill:{skill.id}",
                        source_name="AnalyticalSkill",
                        authority=Authority.GOVERNED,
                        confidence=0.9,
                        version=str(skill.version),
                        scope={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
                        payload={
                            "name": skill.name,
                            "skill_type": skill.skill_type,
                            "plan_template": skill.plan_template,
                            "parameters_schema": skill.parameters_schema or {},
                            "examples": skill.examples or {},
                        },
                    )
                )

        if (
            EvidenceType.KNOWLEDGE in requested_types
            or EvidenceType.BUSINESS_PROCESS in requested_types
            or EvidenceType.DATA_QUALITY in requested_types
            or EvidenceType.SOURCE_POLICY in requested_types
        ):
            if (
                EvidenceType.KNOWLEDGE in requested_types
                or EvidenceType.BUSINESS_PROCESS in requested_types
            ):
                claims = list(
                    (
                        await self.db.execute(
                            select(KnowledgeClaim)
                            .where(
                                KnowledgeClaim.tenant_id == scope.tenant_id,
                                KnowledgeClaim.workspace_id == scope.workspace_id,
                                KnowledgeClaim.status == "published",
                            )
                            .limit(100)
                        )
                    )
                    .scalars()
                    .all()
                )
                claims.sort(
                    key=lambda claim_row: _score(
                        question_tokens, claim_row.text, claim_row.normalized_text
                    ),
                    reverse=True,
                )
                for claim_row in claims[:20]:
                    is_process = str(claim_row.claim_type or "").lower() in {
                        "procedure",
                        "process",
                        "business_process",
                        "workflow",
                    }
                    if is_process and EvidenceType.BUSINESS_PROCESS in requested_types:
                        claim_evidence_type = EvidenceType.BUSINESS_PROCESS
                    elif EvidenceType.KNOWLEDGE in requested_types:
                        claim_evidence_type = EvidenceType.KNOWLEDGE
                    elif EvidenceType.BUSINESS_PROCESS in requested_types:
                        claim_evidence_type = EvidenceType.BUSINESS_PROCESS
                    else:
                        continue
                    items.append(
                        EvidenceItem(
                            type=claim_evidence_type,
                            source_id=f"knowledge-claim:{claim_row.id}",
                            source_name="KnowledgeClaim",
                            authority=Authority.CONTEXTUAL,
                            confidence=float(claim_row.confidence or 0.5),
                            version=str(claim_row.source_version_id),
                            scope={
                                "tenant_id": scope.tenant_id,
                                "workspace_id": scope.workspace_id,
                            },
                            payload={
                                "claim_type": claim_row.claim_type,
                                "text": claim_row.text,
                                "metadata": claim_row.claim_metadata or {},
                            },
                            citation=claim_row.evidence_chunk_id,
                        )
                    )
            semantic_assets = list(
                (
                    await self.db.execute(
                        select(Text2SQLSemanticAsset).where(
                            Text2SQLSemanticAsset.tenant_id == scope.tenant_id,
                            Text2SQLSemanticAsset.workspace_id == scope.workspace_id,
                            Text2SQLSemanticAsset.data_source_id == self.data_source.id,
                            Text2SQLSemanticAsset.status == "published",
                            or_(
                                Text2SQLSemanticAsset.project_id.is_(None),
                                Text2SQLSemanticAsset.project_id == scope.project_id,
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            asset_types = {
                "business_process": EvidenceType.BUSINESS_PROCESS,
                "data_quality": EvidenceType.DATA_QUALITY,
                "entity": EvidenceType.ENTITY,
                "dimension": EvidenceType.ENTITY,
                "source_policy": EvidenceType.SOURCE_POLICY,
            }
            for semantic_asset in semantic_assets:
                evidence_type = asset_types.get(semantic_asset.asset_type)
                if evidence_type is None or evidence_type not in requested_types:
                    continue
                items.append(
                    EvidenceItem(
                        type=evidence_type,
                        source_id=f"semantic-asset:{semantic_asset.id}",
                        source_name="Text2SQLSemanticAsset",
                        authority=Authority.GOVERNED,
                        confidence=1.0,
                        version=str(semantic_asset.version),
                        scope={
                            "tenant_id": scope.tenant_id,
                            "workspace_id": scope.workspace_id,
                            "data_source_id": self.data_source.id,
                        },
                        payload={
                            "asset_key": semantic_asset.asset_key,
                            "title": semantic_asset.title,
                            "description": semantic_asset.description,
                            **(semantic_asset.definition_json or {}),
                        },
                        citation=(semantic_asset.source_refs or [None])[0],
                    )
                )
        return EvidenceBundle(
            items=items,
            schema_fingerprint=schema_fingerprint,
            dialect=dialect,
            database_name=str(self.data_source.database or ""),
            table_columns=inspection.column_map,
            collection_warnings=[] if inspection.column_map else ["Schema 快照为空"],
        )
