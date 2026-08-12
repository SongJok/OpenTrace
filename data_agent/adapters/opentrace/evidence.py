"""OpenTrace 数据目录、语义资产和知识库适配器。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from data_agent.contracts import (
    Authority,
    DataScope,
    EvidenceBundle,
    EvidenceItem,
    EvidenceType,
    ResearchPlan,
)
from infra.metadata.schema_inspector import load_schema_inspection
from infra.storage.data_agent_models import (
    DataAgentLearningPattern,
    DataAgentProfile,
    DataAgentRunRecord,
    DataAgentSemanticAsset,
)
from infra.storage.models import (
    AnalyticalSkill,
    DataSource,
    KnowledgeClaim,
    MetricDefinition,
    SchemaMetadata,
    SchemaTableMetadata,
    TableRelationship,
)
from services.sql_assets import retrieve_sql_assets


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


def _authority(value: str | None) -> Authority:
    try:
        return Authority(str(value or "contextual"))
    except ValueError:
        return Authority.CONTEXTUAL


def _active_at(valid_from: Any, valid_to: Any, reference: datetime) -> bool:
    start = valid_from
    end = valid_to
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return not ((start and reference < start) or (end and reference >= end))


def _numeric_result_summary(result_json: dict[str, Any]) -> dict[str, Any]:
    rows = result_json.get("rows") or []
    values: dict[str, list[float]] = {}
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if isinstance(value, int | float) and not isinstance(value, bool):
                values.setdefault(str(key), []).append(float(value))
    return {
        key: {
            "min": min(items),
            "max": max(items),
            "avg": sum(items) / len(items),
            "count": len(items),
        }
        for key, items in values.items()
        if items
    }


class OpenTraceEvidenceProvider:
    def __init__(self, db: AsyncSession, data_source: DataSource) -> None:
        self.db = db
        self.data_source = data_source

    async def collect(self, scope: DataScope, question: str, plan: ResearchPlan) -> EvidenceBundle:
        inspection = await load_schema_inspection(self.db, self.data_source.id)
        dialect = str(self.data_source.source_type or "mysql").lower()
        reference_time = datetime.now(UTC)
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

        profile_rows = list(
            (
                await self.db.execute(
                    select(DataAgentProfile)
                    .where(
                        DataAgentProfile.user_id == scope.user_id,
                        DataAgentProfile.tenant_id == scope.tenant_id,
                        DataAgentProfile.workspace_id == scope.workspace_id,
                        DataAgentProfile.data_source_id == self.data_source.id,
                        DataAgentProfile.schema_fingerprint == schema_fingerprint,
                        DataAgentProfile.status == "current",
                        or_(
                            DataAgentProfile.expires_at.is_(None),
                            DataAgentProfile.expires_at > reference_time,
                        ),
                    )
                    .order_by(DataAgentProfile.profiled_at.desc())
                )
            )
            .scalars()
            .all()
        )
        latest_profiles: dict[tuple[str, str], DataAgentProfile] = {}
        for profile_row in profile_rows:
            latest_profiles.setdefault(
                (profile_row.table_name, profile_row.column_name), profile_row
            )
        for profile_row in latest_profiles.values():
            if profile_row.profile_type != "column":
                continue
            profile_payload = dict(profile_row.profile_json or {})
            items.append(
                EvidenceItem(
                    type=EvidenceType.COLUMN_PROFILE,
                    source_id=f"data-profile:{profile_row.id}",
                    source_name="DataAgentProfile",
                    authority=Authority.LIVE_SYSTEM,
                    confidence=0.78,
                    version=profile_row.schema_fingerprint,
                    scope={"data_source_id": self.data_source.id},
                    sensitive=bool(profile_payload.get("sensitive")),
                    payload={
                        "table": profile_row.table_name,
                        "column": profile_row.column_name,
                        "profiled_at": (
                            profile_row.profiled_at.isoformat() if profile_row.profiled_at else None
                        ),
                        **profile_payload,
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
            certified = bool(
                metric_row.certification_level == "certified"
                and metric_row.approved_by
                and metric_row.owner
                and metric_row.evidence_refs
            )
            items.append(
                EvidenceItem(
                    type=EvidenceType.METRIC,
                    source_id=f"metric:{metric_row.id}",
                    source_name="MetricDefinition",
                    authority=Authority.GOVERNED if certified else Authority.VERIFIED,
                    confidence=1.0 if certified else 0.82,
                    version=str(metric_row.version),
                    scope={"data_source_id": self.data_source.id},
                    payload={
                        "name": metric_row.name,
                        "aliases": metric_row.aliases or [],
                        "formula": metric_row.formula,
                        "underlying_columns": metric_row.underlying_columns or [],
                        "aggregation": metric_row.agg_function,
                        "business_definition": metric_row.business_definition,
                        "required_filters": metric_row.required_filters
                        or (
                            (metric_row.business_definition or "")
                            .split(";固有过滤：", 1)[-1]
                            .split(";")
                            if "固有过滤：" in (metric_row.business_definition or "")
                            else []
                        ),
                        "time_field": metric_row.time_field,
                        "grain": metric_row.grain,
                        "owner": metric_row.owner,
                        "business_domain": metric_row.business_domain,
                        "unit": metric_row.unit,
                        "version": metric_row.version,
                        "certification_level": metric_row.certification_level,
                        "evidence_refs": metric_row.evidence_refs or [],
                        "quality_contract": metric_row.quality_contract or {},
                    },
                    valid_from=metric_row.valid_from,
                    valid_to=metric_row.valid_to,
                )
            )
            if metric_row.quality_contract:
                items.append(
                    EvidenceItem(
                        type=EvidenceType.DATA_QUALITY,
                        source_id=f"metric-quality:{metric_row.id}",
                        source_name="MetricDefinition",
                        authority=Authority.GOVERNED if certified else Authority.VERIFIED,
                        confidence=1.0 if certified else 0.82,
                        version=str(metric_row.version),
                        scope={"data_source_id": self.data_source.id},
                        payload={
                            **(metric_row.quality_contract or {}),
                            "metric": metric_row.name,
                        },
                        citation=next(
                            (
                                str(item)
                                for item in metric_row.evidence_refs or []
                                if str(item).strip()
                            ),
                            None,
                        ),
                        valid_from=metric_row.valid_from,
                        valid_to=metric_row.valid_to,
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
            or EvidenceType.BUSINESS_RULE in requested_types
            or EvidenceType.POLICY in requested_types
            or EvidenceType.REPORT in requested_types
            or EvidenceType.LINEAGE in requested_types
            or EvidenceType.DATA_QUALITY in requested_types
            or EvidenceType.SOURCE_POLICY in requested_types
        ):
            if (
                EvidenceType.KNOWLEDGE in requested_types
                or EvidenceType.BUSINESS_PROCESS in requested_types
                or EvidenceType.BUSINESS_RULE in requested_types
                or EvidenceType.POLICY in requested_types
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
                    claim_type = str(claim_row.claim_type or "").lower()
                    if (
                        claim_type in {"rule", "business_rule"}
                        and EvidenceType.BUSINESS_RULE in requested_types
                    ):
                        claim_evidence_type = EvidenceType.BUSINESS_RULE
                    elif (
                        claim_type in {"policy", "business_policy"}
                        and EvidenceType.POLICY in requested_types
                    ):
                        claim_evidence_type = EvidenceType.POLICY
                    elif is_process and EvidenceType.BUSINESS_PROCESS in requested_types:
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
                        select(DataAgentSemanticAsset).where(
                            DataAgentSemanticAsset.tenant_id == scope.tenant_id,
                            DataAgentSemanticAsset.workspace_id == scope.workspace_id,
                            DataAgentSemanticAsset.data_source_id == self.data_source.id,
                            DataAgentSemanticAsset.status == "published",
                        )
                    )
                )
                .scalars()
                .all()
            )
            asset_types = {
                "business_process": EvidenceType.BUSINESS_PROCESS,
                "business_rule": EvidenceType.BUSINESS_RULE,
                "policy": EvidenceType.POLICY,
                "report": EvidenceType.REPORT,
                "lineage": EvidenceType.LINEAGE,
                "data_quality": EvidenceType.DATA_QUALITY,
                "entity": EvidenceType.ENTITY,
                "dimension": EvidenceType.ENTITY,
                "source_policy": EvidenceType.SOURCE_POLICY,
            }
            for semantic_asset in semantic_assets:
                evidence_type = asset_types.get(semantic_asset.asset_type)
                if evidence_type is None or evidence_type not in requested_types:
                    continue
                if evidence_type == EvidenceType.SOURCE_POLICY and not _active_at(
                    semantic_asset.valid_from,
                    semantic_asset.valid_to,
                    reference_time,
                ):
                    continue
                items.append(
                    EvidenceItem(
                        type=evidence_type,
                        source_id=f"semantic-asset:{semantic_asset.id}",
                        source_name="DataAgentSemanticAsset",
                        authority=_authority(semantic_asset.authority),
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
                            "business_domain": semantic_asset.business_domain,
                            "owner": semantic_asset.owner,
                            **(semantic_asset.definition_json or {}),
                        },
                        citation=(semantic_asset.source_refs or [None])[0],
                        valid_from=semantic_asset.valid_from,
                        valid_to=semantic_asset.valid_to,
                    )
                )

        if EvidenceType.EXECUTION_MEMORY in requested_types:
            current_semantic_version = self._semantic_version(items)
            learning_rows = list(
                (
                    await self.db.execute(
                        select(DataAgentLearningPattern)
                        .where(
                            DataAgentLearningPattern.user_id == scope.user_id,
                            DataAgentLearningPattern.tenant_id == scope.tenant_id,
                            DataAgentLearningPattern.workspace_id == scope.workspace_id,
                            DataAgentLearningPattern.data_source_id == self.data_source.id,
                            DataAgentLearningPattern.scope_key == "__global__",
                            DataAgentLearningPattern.schema_fingerprint == schema_fingerprint,
                            DataAgentLearningPattern.semantic_version == current_semantic_version,
                            DataAgentLearningPattern.status.in_(["observed", "trusted"]),
                        )
                        .order_by(DataAgentLearningPattern.last_verified_at.desc())
                        .limit(100)
                    )
                )
                .scalars()
                .all()
            )
            learning_rows.sort(
                key=lambda row: _score(
                    question_tokens,
                    row.question_examples,
                    row.logical_plan_json,
                ),
                reverse=True,
            )
            for learning_row in learning_rows[:10]:
                relevance = _score(
                    question_tokens,
                    learning_row.question_examples,
                    learning_row.logical_plan_json,
                )
                if relevance <= 0:
                    continue
                items.append(
                    EvidenceItem(
                        type=EvidenceType.EXECUTION_MEMORY,
                        source_id=f"learning-pattern:{learning_row.id}",
                        source_name="DataAgentLearningPattern",
                        authority=(
                            Authority.VERIFIED
                            if learning_row.status == "trusted"
                            else Authority.CONTEXTUAL
                        ),
                        confidence=float(learning_row.confidence or 0.0),
                        version=learning_row.semantic_version,
                        scope={
                            "tenant_id": scope.tenant_id,
                            "workspace_id": scope.workspace_id,
                            "data_source_id": self.data_source.id,
                        },
                        payload={
                            "pattern_key": learning_row.pattern_key,
                            "question_examples": learning_row.question_examples or [],
                            "logical_plan": learning_row.logical_plan_json or {},
                            "sql_structure_hash": learning_row.sql_structure_hash,
                            "status": learning_row.status,
                            "observation_count": learning_row.observation_count,
                            "success_count": learning_row.success_count,
                            "failure_count": learning_row.failure_count,
                        },
                        citation=learning_row.last_run_id,
                    )
                )
            memory_rows = list(
                (
                    await self.db.execute(
                        select(DataAgentRunRecord)
                        .where(
                            DataAgentRunRecord.user_id == scope.user_id,
                            DataAgentRunRecord.tenant_id == scope.tenant_id,
                            DataAgentRunRecord.workspace_id == scope.workspace_id,
                            DataAgentRunRecord.data_source_id == self.data_source.id,
                            DataAgentRunRecord.state == "completed",
                            DataAgentRunRecord.schema_fingerprint == schema_fingerprint,
                            DataAgentRunRecord.semantic_version == current_semantic_version,
                        )
                        .order_by(DataAgentRunRecord.completed_at.desc())
                        .limit(30)
                    )
                )
                .scalars()
                .all()
            )
            memory_rows.sort(
                key=lambda row: _score(
                    question_tokens,
                    row.question,
                    row.logical_plan_json,
                ),
                reverse=True,
            )
            for memory_row in memory_rows[:5]:
                learning_status = str((memory_row.learning_json or {}).get("status") or "")
                result_payload = dict(memory_row.result_json or {})
                if (
                    learning_status not in {"observed", "trusted"}
                    or (memory_row.result_validation_json or {}).get("status") != "pass"
                    or not result_payload.get("rows")
                    or bool(result_payload.get("truncated"))
                ):
                    continue
                if _score(question_tokens, memory_row.question, memory_row.logical_plan_json) <= 0:
                    continue
                items.append(
                    EvidenceItem(
                        type=EvidenceType.EXECUTION_MEMORY,
                        source_id=f"data-agent-run:{memory_row.id}",
                        source_name="DataAgentRunRecord",
                        authority=Authority.VERIFIED,
                        confidence=0.85,
                        version=memory_row.schema_fingerprint,
                        scope={
                            "tenant_id": scope.tenant_id,
                            "workspace_id": scope.workspace_id,
                            "data_source_id": self.data_source.id,
                        },
                        payload={
                            "question": memory_row.question,
                            "logical_plan": memory_row.logical_plan_json or {},
                            "selected_candidate_id": memory_row.selected_candidate_id,
                            "result_validation": memory_row.result_validation_json or {},
                            "numeric_result_summary": _numeric_result_summary(
                                memory_row.result_json or {}
                            ),
                        },
                        citation=memory_row.id,
                    )
                )

        authority_conflicts = self._authority_conflicts(items)
        semantic_version = self._semantic_version(items)
        latest_profiled_at = max(
            (
                profile.profiled_at
                for profile in latest_profiles.values()
                if profile.profiled_at is not None
            ),
            default=None,
        )
        return EvidenceBundle(
            items=items,
            schema_fingerprint=schema_fingerprint,
            dialect=dialect,
            database_name=str(self.data_source.database or ""),
            table_columns=inspection.column_map,
            semantic_version=semantic_version,
            data_freshness={
                "profiled_at": latest_profiled_at.isoformat() if latest_profiled_at else None,
                "profile_status": "current" if latest_profiled_at else "missing",
            },
            authority_conflicts=authority_conflicts,
            collection_warnings=[] if inspection.column_map else ["Schema 快照为空"],
        )

    @staticmethod
    def _semantic_version(items: list[EvidenceItem]) -> str:
        semantic_types = {
            EvidenceType.METRIC,
            EvidenceType.ENTITY,
            EvidenceType.RELATIONSHIP,
            EvidenceType.BUSINESS_PROCESS,
            EvidenceType.BUSINESS_RULE,
            EvidenceType.POLICY,
            EvidenceType.REPORT,
            EvidenceType.LINEAGE,
            EvidenceType.KNOWLEDGE,
            EvidenceType.DATA_QUALITY,
            EvidenceType.SKILL,
            EvidenceType.SOURCE_POLICY,
        }
        semantic_versions = []
        for item in items:
            if item.type not in semantic_types:
                continue
            payload_hash = hashlib.sha256(
                json.dumps(
                    item.payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            semantic_versions.append(
                ":".join(
                    (
                        item.type.value,
                        item.source_id,
                        item.authority.value,
                        item.version or "",
                        payload_hash,
                    )
                )
            )
        semantic_versions.sort()
        return hashlib.sha256("|".join(semantic_versions).encode("utf-8")).hexdigest()

    @staticmethod
    def _authority_conflicts(items: list[EvidenceItem]) -> list[dict[str, Any]]:
        grouped: dict[tuple[EvidenceType, str], list[EvidenceItem]] = {}
        for item in items:
            if item.type not in {
                EvidenceType.METRIC,
                EvidenceType.BUSINESS_RULE,
                EvidenceType.POLICY,
                EvidenceType.SOURCE_POLICY,
            }:
                continue
            key = str(
                item.payload.get("name")
                or item.payload.get("asset_key")
                or item.payload.get("title")
                or item.source_id
            ).lower()
            grouped.setdefault((item.type, key), []).append(item)
        conflicts: list[dict[str, Any]] = []
        for (item_type, key), values in grouped.items():
            governed = [
                item
                for item in values
                if item.authority in {Authority.LIVE_SYSTEM, Authority.GOVERNED, Authority.VERIFIED}
            ]
            overlapping_conflict = any(
                json.dumps(left.payload, ensure_ascii=False, sort_keys=True, default=str)
                != json.dumps(right.payload, ensure_ascii=False, sort_keys=True, default=str)
                and OpenTraceEvidenceProvider._intervals_overlap(left, right)
                for index, left in enumerate(governed)
                for right in governed[index + 1 :]
            )
            if overlapping_conflict:
                conflicts.append(
                    {
                        "type": item_type.value,
                        "key": key,
                        "source_ids": [item.source_id for item in governed],
                    }
                )
        return conflicts

    @staticmethod
    def _intervals_overlap(left: EvidenceItem, right: EvidenceItem) -> bool:
        def normalized(value: datetime | None, fallback: datetime) -> datetime:
            result = value or fallback
            return result if result.tzinfo is not None else result.replace(tzinfo=UTC)

        left_start = normalized(left.valid_from, datetime.min.replace(tzinfo=UTC))
        left_end = normalized(left.valid_to, datetime.max.replace(tzinfo=UTC))
        right_start = normalized(right.valid_from, datetime.min.replace(tzinfo=UTC))
        right_end = normalized(right.valid_to, datetime.max.replace(tzinfo=UTC))
        return left_start < right_end and right_start < left_end
