"""独立 DataAgent 平台的 OpenTrace 适配 API。"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from data_agent.adapters.opentrace.answer import OpenTraceAnswerSynthesizer
from data_agent.adapters.opentrace.evidence import OpenTraceEvidenceProvider
from data_agent.adapters.opentrace.executor import OpenTraceQueryExecutor
from data_agent.adapters.opentrace.generator import OpenTraceSQLGenerator
from data_agent.adapters.opentrace.learning import OpenTraceLearningRepository
from data_agent.adapters.opentrace.repository import OpenTraceRunRepository
from data_agent.adapters.opentrace.source_resolution import OpenTraceSourceResolver
from data_agent.contracts import (
    DataScope,
    DataSourceDecision,
    ExecutionMode,
    QueryRequest,
    deterministic_run_id,
)
from data_agent.evaluation import PlanComparator, ResultComparator
from data_agent.learning import ExecutionLearningEngine, sql_structure_hash
from data_agent.profiling import DataProfiler, serialize_profile
from data_agent.service import DataAgentService
from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.config.settings import settings
from infra.storage.data_agent_models import (
    DataAgentEvaluationCase,
    DataAgentEvaluationSuiteRun,
    DataAgentFailurePattern,
    DataAgentFeedback,
    DataAgentLearningPattern,
    DataAgentProfile,
    DataAgentResultArtifact,
    DataAgentRunRecord,
    DataAgentSemanticAsset,
)
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User


def _ensure_enabled() -> None:
    if not settings.data_agent_enabled:
        raise HTTPException(status_code=404, detail="DataAgent 未启用")


router = APIRouter(dependencies=[Depends(_ensure_enabled)])

_GOVERNANCE_RUN_ANALYSIS_LIMIT = 10_000


class DataAgentQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8192)
    data_source_id: str | None = Field(default=None, min_length=1, max_length=128)
    mode: str = Field(default="sql_only", pattern="^(sql_only|execute_and_answer)$")
    confirmed: bool = False
    clarification_context: str | None = Field(default=None, max_length=4000)
    candidate_count: int = Field(default=3, ge=1, le=5)
    max_rows: int = Field(default=100, ge=1, le=10000)
    requested_tables: list[str] = Field(default_factory=list, max_length=100)
    requested_output: str | None = Field(default=None, max_length=1000)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    as_of: datetime | None = None
    minimum_confidence: float = Field(default=0.75, ge=0.0, le=1.0)


class DataAgentExecuteRequest(BaseModel):
    candidate_id: str | None = Field(default=None, max_length=64)
    confirmed: bool = True


class SemanticAssetCreateRequest(BaseModel):
    data_source_id: str = Field(..., min_length=1, max_length=128)
    asset_type: str = Field(
        ...,
        pattern=(
            "^(business_process|business_rule|policy|report|lineage|data_quality|entity|"
            "dimension|source_policy)$"
        ),
    )
    asset_key: str = Field(..., min_length=1, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    definition: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list, max_length=50)
    business_domain: str | None = Field(default=None, max_length=128)
    owner: str | None = Field(default=None, max_length=255)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class EvaluationCaseCreateRequest(BaseModel):
    data_source_id: str = Field(..., min_length=1, max_length=128)
    question: str = Field(..., min_length=1, max_length=8192)
    expected_sql: str | None = None
    expected_plan: dict[str, Any] = Field(default_factory=dict)
    expected_result: list[dict[str, Any]] = Field(default_factory=list)
    schema_fingerprint: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    business_domain: str | None = Field(default=None, max_length=128)


class FeedbackRequest(BaseModel):
    verdict: str = Field(..., pattern="^(correct|incorrect|needs_clarification)$")
    candidate_id: str | None = Field(default=None, max_length=64)
    corrected_sql: str | None = Field(default=None, max_length=20000)
    comment: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileRefreshRequest(BaseModel):
    data_source_id: str = Field(..., min_length=1, max_length=128)
    tables: list[str] = Field(default_factory=list, max_length=1000)


class EvaluationRunRequest(BaseModel):
    execute: bool = False
    max_rows: int = Field(default=500, ge=1, le=10000)


class EvaluationSuiteRunRequest(BaseModel):
    data_source_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(default="发布门禁", min_length=1, max_length=255)
    execute: bool = False
    max_rows: int = Field(default=500, ge=1, le=10000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    business_domain: str | None = Field(default=None, max_length=128)
    minimum_pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)


class GovernanceResolveRequest(BaseModel):
    status: str = Field(..., pattern="^(resolved|ignored)$")
    resolution_note: str = Field(..., min_length=1, max_length=4000)


class SourceResolutionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8192)
    data_source_id: str | None = Field(default=None, min_length=1, max_length=128)
    candidate_data_source_ids: list[str] = Field(default_factory=list, max_length=100)


def _scope(request: Request, user: User, data_source_id: str) -> DataScope:
    metadata = build_tenant_metadata(request, user_id=user.id)
    return DataScope(
        user_id=user.id,
        tenant_id=str(metadata.get("tenant_id") or "default"),
        workspace_id=str(metadata.get("workspace_id") or "default"),
        data_source_id=data_source_id,
    )


def _service(
    db: AsyncSession,
    source: Any,
    *,
    learning_enabled: bool = True,
) -> DataAgentService:
    return DataAgentService(
        evidence_provider=OpenTraceEvidenceProvider(db, source),
        sql_generator=OpenTraceSQLGenerator(),
        query_executor=OpenTraceQueryExecutor(source),
        answer_synthesizer=OpenTraceAnswerSynthesizer(),
        repository=OpenTraceRunRepository(db),
        learning_repository=(
            OpenTraceLearningRepository(db)
            if settings.data_agent_learning_enabled and learning_enabled
            else None
        ),
        learning_engine=ExecutionLearningEngine(
            minimum_confidence=settings.data_agent_learning_min_confidence
        ),
    )


def _payload(run) -> dict[str, Any]:
    return run.model_dump(mode="json")


async def _source_for_scope(
    request: Request,
    user: User,
    db: AsyncSession,
    data_source_id: str,
    permission: str,
):
    scope = _scope(request, user, data_source_id)
    source = await get_accessible_data_source(
        db,
        user_id=user.id,
        tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
        data_source_id=data_source_id,
        required_permission=permission,
        active_only=True,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="data source not found")
    return scope, source


def _validate_max_rows(max_rows: int) -> None:
    if max_rows > settings.data_agent_max_result_rows:
        raise HTTPException(
            status_code=422,
            detail=f"max_rows 不能超过平台上限 {settings.data_agent_max_result_rows}",
        )


def _validate_effective_interval(valid_from: datetime | None, valid_to: datetime | None) -> None:
    if valid_from is None or valid_to is None:
        return
    start = valid_from if valid_from.tzinfo is not None else valid_from.replace(tzinfo=UTC)
    end = valid_to if valid_to.tzinfo is not None else valid_to.replace(tzinfo=UTC)
    if end <= start:
        raise HTTPException(status_code=422, detail="valid_to 必须晚于 valid_from")


def _ensure_data_governance_admin(current_user: User) -> None:
    if not (current_user.is_superuser or current_user.role == "admin"):
        raise HTTPException(status_code=403, detail="只有管理员可以执行问数治理操作")


@router.post("/data-agent/queries")
async def create_data_agent_query(
    request: Request,
    payload: DataAgentQueryRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_metadata = build_tenant_metadata(request, user_id=current_user.id)
    decision = await OpenTraceSourceResolver(db).resolve(
        question=payload.question,
        user_id=current_user.id,
        tenant_id=str(tenant_metadata.get("tenant_id") or "default"),
        workspace_id=str(tenant_metadata.get("workspace_id") or "default"),
        explicit_id=payload.data_source_id,
    )
    if decision.status != "selected" or not decision.selected_data_source_id:
        return {
            "state": decision.status,
            "needs_clarification": decision.status == "needs_clarification",
            "source_decision": decision.model_dump(mode="json"),
        }
    selected_source_id = decision.selected_data_source_id
    scope = _scope(request, current_user, selected_source_id)
    _validate_max_rows(payload.max_rows)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
        data_source_id=selected_source_id,
        required_permission="query",
        active_only=True,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="data source not found")
    normalized_idempotency_key = str(idempotency_key or "").strip() or None
    if normalized_idempotency_key and len(normalized_idempotency_key) > 255:
        raise HTTPException(status_code=422, detail="Idempotency-Key 不能超过 255 个字符")
    query = QueryRequest(
        question=payload.question,
        scope=scope,
        mode=ExecutionMode(payload.mode),
        confirmed=payload.confirmed,
        clarification_context=payload.clarification_context,
        candidate_count=payload.candidate_count,
        max_rows=payload.max_rows,
        requested_tables=payload.requested_tables,
        requested_output=payload.requested_output,
        timezone=payload.timezone,
        as_of=payload.as_of,
        minimum_confidence=payload.minimum_confidence,
        idempotency_key=normalized_idempotency_key,
        source_decision=decision,
    )
    if normalized_idempotency_key:
        existing = await OpenTraceRunRepository(db).get(deterministic_run_id(query), scope)
        if existing is not None:
            if existing.request != query:
                raise HTTPException(status_code=409, detail="Idempotency-Key 已用于不同请求")
            return _payload(existing)
    run = await _service(db, source).create(query)
    return _payload(run)


@router.post("/data-agent/source-resolution")
async def resolve_data_agent_source(
    request: Request,
    payload: SourceResolutionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    metadata = build_tenant_metadata(request, user_id=current_user.id)
    decision = await OpenTraceSourceResolver(db).resolve(
        question=payload.question,
        user_id=current_user.id,
        tenant_id=str(metadata.get("tenant_id") or "default"),
        workspace_id=str(metadata.get("workspace_id") or "default"),
        explicit_id=payload.data_source_id,
        candidate_ids=payload.candidate_data_source_ids,
    )
    return {"source_decision": decision.model_dump(mode="json")}


@router.get("/data-agent/queries/{run_id}")
async def get_data_agent_query(
    request: Request,
    run_id: str,
    data_source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, data_source_id)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
        data_source_id=data_source_id,
        required_permission="view",
        active_only=True,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="data source not found")
    run = await OpenTraceRunRepository(db).get(run_id, scope)
    if run is None:
        raise HTTPException(status_code=404, detail="DataAgent run not found")
    return _payload(run)


@router.get("/data-agent/queries/{run_id}/result-artifact")
async def get_data_agent_result_artifact(
    request: Request,
    run_id: str,
    data_source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope, _ = await _source_for_scope(request, current_user, db, data_source_id, "view")
    artifact = await db.scalar(
        select(DataAgentResultArtifact)
        .where(
            DataAgentResultArtifact.run_id == run_id,
            DataAgentResultArtifact.user_id == scope.user_id,
            DataAgentResultArtifact.tenant_id == scope.tenant_id,
            DataAgentResultArtifact.workspace_id == scope.workspace_id,
            DataAgentResultArtifact.data_source_id == scope.data_source_id,
        )
        .order_by(DataAgentResultArtifact.created_at.desc())
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="DataAgent result artifact not found")
    return {
        "id": artifact.id,
        "run_id": artifact.run_id,
        "data_source_id": artifact.data_source_id,
        "sql_structure_hash": artifact.sql_structure_hash,
        "result_signature": artifact.result_signature,
        "schema_fingerprint": artifact.schema_fingerprint,
        "semantic_version": artifact.semantic_version,
        "returned_rows": artifact.returned_rows,
        "total_rows": artifact.total_rows,
        "truncated": artifact.truncated,
        "columns": list(artifact.columns_json or []),
        "validation": dict(artifact.validation_json or {}),
        "freshness": dict(artifact.freshness_json or {}),
        "details_purged": artifact.details_purged_at is not None,
        "details_purged_at": (
            artifact.details_purged_at.isoformat() if artifact.details_purged_at else None
        ),
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "expires_at": artifact.expires_at.isoformat() if artifact.expires_at else None,
    }


@router.post("/data-agent/queries/{run_id}/execute")
async def execute_data_agent_query(
    request: Request,
    run_id: str,
    payload: DataAgentExecuteRequest,
    data_source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, data_source_id)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
        data_source_id=data_source_id,
        required_permission="query",
        active_only=True,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="data source not found")
    try:
        run = await _service(db, source).execute(
            run_id, scope, candidate_id=payload.candidate_id, confirmed=payload.confirmed
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _payload(run)


@router.post("/data-agent/semantic-assets")
async def create_semantic_asset(
    request: Request,
    payload: SemanticAssetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope, _ = await _source_for_scope(request, current_user, db, payload.data_source_id, "edit")
    _validate_effective_interval(payload.valid_from, payload.valid_to)
    latest_version = await db.scalar(
        select(func.max(DataAgentSemanticAsset.version)).where(
            DataAgentSemanticAsset.tenant_id == scope.tenant_id,
            DataAgentSemanticAsset.workspace_id == scope.workspace_id,
            DataAgentSemanticAsset.data_source_id == payload.data_source_id,
            DataAgentSemanticAsset.asset_type == payload.asset_type,
            DataAgentSemanticAsset.asset_key == payload.asset_key,
        )
    )
    asset = DataAgentSemanticAsset(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        data_source_id=payload.data_source_id,
        asset_type=payload.asset_type,
        asset_key=payload.asset_key,
        version=int(latest_version or 0) + 1,
        title=payload.title,
        description=payload.description,
        definition_json=payload.definition,
        source_refs=payload.source_refs,
        business_domain=payload.business_domain,
        owner=payload.owner,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        authority="contextual",
        status="draft",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return {"asset": _semantic_asset_payload(asset)}


@router.get("/data-agent/semantic-assets")
async def list_semantic_assets(
    request: Request,
    data_source_id: str = Query(..., min_length=1),
    asset_type: str | None = Query(default=None),
    status: str = Query(default="published"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, data_source_id)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
        data_source_id=data_source_id,
        required_permission="view",
        active_only=True,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="data source not found")
    statement = select(DataAgentSemanticAsset).where(
        DataAgentSemanticAsset.tenant_id == scope.tenant_id,
        DataAgentSemanticAsset.workspace_id == scope.workspace_id,
        DataAgentSemanticAsset.data_source_id == data_source_id,
    )
    if asset_type:
        statement = statement.where(DataAgentSemanticAsset.asset_type == asset_type)
    if status:
        statement = statement.where(DataAgentSemanticAsset.status == status)
    rows = list(
        (await db.execute(statement.order_by(DataAgentSemanticAsset.updated_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return {"items": [_semantic_asset_payload(row) for row in rows], "total": len(rows)}


@router.post("/data-agent/semantic-assets/{asset_id}/publish")
async def publish_semantic_asset(
    request: Request,
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    asset = await db.scalar(
        select(DataAgentSemanticAsset).where(
            DataAgentSemanticAsset.id == asset_id,
            DataAgentSemanticAsset.tenant_id
            == str(
                build_tenant_metadata(request, user_id=current_user.id).get("tenant_id")
                or "default"
            ),
            DataAgentSemanticAsset.workspace_id
            == str(
                build_tenant_metadata(request, user_id=current_user.id).get("workspace_id")
                or "default"
            ),
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="semantic asset not found")
    await _source_for_scope(request, current_user, db, asset.data_source_id, "edit")
    if not (current_user.is_superuser or current_user.role == "admin"):
        raise HTTPException(
            status_code=403, detail="only an administrator can publish semantic assets"
        )
    if asset.status != "draft":
        raise HTTPException(status_code=409, detail="只有草稿治理资产可以发布")
    _validate_effective_interval(asset.valid_from, asset.valid_to)
    asset.status = "published"
    asset.authority = "governed"
    asset.approved_by = current_user.id
    asset.approved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(asset)
    return {"asset": _semantic_asset_payload(asset)}


@router.post("/data-agent/evaluation-cases")
async def create_evaluation_case(
    request: Request,
    payload: EvaluationCaseCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_data_governance_admin(current_user)
    scope, _ = await _source_for_scope(request, current_user, db, payload.data_source_id, "edit")
    case = DataAgentEvaluationCase(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        data_source_id=payload.data_source_id,
        question=payload.question,
        expected_sql=payload.expected_sql,
        expected_plan=payload.expected_plan,
        expected_result=payload.expected_result,
        schema_fingerprint=payload.schema_fingerprint,
        tags=payload.tags,
        business_domain=payload.business_domain,
        status="draft",
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return {"case": _evaluation_case_payload(case)}


@router.get("/data-agent/evaluation-cases")
async def list_evaluation_cases(
    request: Request,
    data_source_id: str = Query(..., min_length=1),
    status: str = Query(default="", pattern="^(|draft|published|retired)$"),
    business_domain: str | None = Query(default=None, max_length=128),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_data_governance_admin(current_user)
    scope, _ = await _source_for_scope(request, current_user, db, data_source_id, "view")
    statement = select(DataAgentEvaluationCase).where(
        DataAgentEvaluationCase.tenant_id == scope.tenant_id,
        DataAgentEvaluationCase.workspace_id == scope.workspace_id,
        DataAgentEvaluationCase.data_source_id == data_source_id,
    )
    if status:
        statement = statement.where(DataAgentEvaluationCase.status == status)
    if business_domain:
        statement = statement.where(DataAgentEvaluationCase.business_domain == business_domain)
    rows = list(
        (await db.execute(statement.order_by(DataAgentEvaluationCase.updated_at.desc()).limit(500)))
        .scalars()
        .all()
    )
    return {"items": [_evaluation_case_payload(row) for row in rows], "total": len(rows)}


@router.post("/data-agent/evaluation-cases/{case_id}/publish")
async def publish_evaluation_case(
    request: Request,
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_data_governance_admin(current_user)
    tenant = build_tenant_metadata(request, user_id=current_user.id)
    case = await db.scalar(
        select(DataAgentEvaluationCase).where(
            DataAgentEvaluationCase.id == case_id,
            DataAgentEvaluationCase.tenant_id == str(tenant.get("tenant_id") or "default"),
            DataAgentEvaluationCase.workspace_id == str(tenant.get("workspace_id") or "default"),
        )
    )
    if case is None:
        raise HTTPException(status_code=404, detail="evaluation case not found")
    await _source_for_scope(request, current_user, db, case.data_source_id, "edit")
    if case.status != "draft":
        raise HTTPException(status_code=409, detail="只有草稿 Golden Case 可以发布")
    if not case.schema_fingerprint:
        raise HTTPException(status_code=422, detail="发布前必须冻结 schema_fingerprint")
    if not (case.expected_plan or case.expected_sql or case.expected_result):
        raise HTTPException(status_code=422, detail="Golden Case 至少需要一种期望断言")
    case.status = "published"
    case.published_by = current_user.id
    case.published_at = datetime.now(UTC)
    await db.commit()
    return {"case": _evaluation_case_payload(case)}


@router.post("/data-agent/queries/{run_id}/feedback")
async def submit_data_agent_feedback(
    request: Request,
    run_id: str,
    data_source_id: str,
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, data_source_id)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
        data_source_id=data_source_id,
        required_permission="view",
        active_only=True,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="data source not found")
    run = await OpenTraceRunRepository(db).get(run_id, scope)
    if run is None:
        raise HTTPException(status_code=404, detail="DataAgent run not found")
    positive_feedback = payload.verdict == "correct"
    resolved_at = datetime.now(UTC) if positive_feedback else None
    feedback = DataAgentFeedback(
        id=str(uuid.uuid4()),
        run_id=run_id,
        user_id=current_user.id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        verdict=payload.verdict,
        candidate_id=payload.candidate_id,
        corrected_sql=payload.corrected_sql,
        comment=payload.comment,
        metadata_json=payload.metadata,
        status="resolved" if positive_feedback else "open",
        resolution_note="正向反馈自动归档" if positive_feedback else None,
        resolved_by=current_user.id if positive_feedback else None,
        resolved_at=resolved_at,
    )
    db.add(feedback)
    learning = None
    if settings.data_agent_learning_enabled:
        learning = await OpenTraceLearningRepository(db).record_feedback(
            run,
            verdict=payload.verdict,
            candidate_id=payload.candidate_id,
            corrected_sql=payload.corrected_sql,
        )
    await db.commit()
    return {
        "feedback_id": feedback.id,
        "stored": True,
        "promoted": bool(learning and learning.status == "trusted"),
        "learning": learning.model_dump(mode="json") if learning else None,
    }


@router.get("/data-agent/governance/overview")
async def data_agent_governance_overview(
    request: Request,
    data_source_id: str = Query(..., min_length=1),
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """返回当前 Scope 的真实问数质量、学习、反馈与发布门禁状态。"""

    _ensure_data_governance_admin(current_user)
    scope, _ = await _source_for_scope(request, current_user, db, data_source_id, "view")
    since_at = datetime.now(UTC) - timedelta(days=days)
    run_scope = (
        DataAgentRunRecord.tenant_id == scope.tenant_id,
        DataAgentRunRecord.workspace_id == scope.workspace_id,
        DataAgentRunRecord.data_source_id == data_source_id,
        DataAgentRunRecord.run_purpose == "online",
        DataAgentRunRecord.created_at >= since_at,
    )
    total_runs = int(
        await db.scalar(select(func.count(DataAgentRunRecord.id)).where(*run_scope)) or 0
    )
    run_rows = list(
        (
            await db.execute(
                select(DataAgentRunRecord)
                .where(*run_scope)
                .order_by(DataAgentRunRecord.created_at.desc())
                .limit(_GOVERNANCE_RUN_ANALYSIS_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    state_counts: dict[str, int] = {}
    failure_stages: dict[str, int] = {}
    completed = 0
    verified = 0
    evidence_complete = 0
    durations: list[int] = []
    for row in run_rows:
        state_counts[row.state] = state_counts.get(row.state, 0) + 1
        if row.state == "completed":
            completed += 1
        validation = dict(row.result_validation_json or {})
        if row.state == "completed" and validation.get("status") in {"pass", "warn"}:
            verified += 1
        answer_metadata = dict(row.answer_metadata_json or {})
        coverage = dict(answer_metadata.get("evidence_requirements") or {})
        if coverage and all(bool(value) for value in coverage.values()):
            evidence_complete += 1
        result_payload = dict(row.result_json or {})
        duration = result_payload.get("duration_ms")
        if isinstance(duration, int | float) and duration >= 0:
            durations.append(int(duration))
        for event in row.trace_json or []:
            if not isinstance(event, dict):
                continue
            if event.get("stage") in {"blocked", "failed", "failure_learning"}:
                reason = str(event.get("reason") or event.get("failure_stage") or "unknown")
                failure_stages[reason] = failure_stages.get(reason, 0) + 1

    open_feedback = int(
        await db.scalar(
            select(func.count(DataAgentFeedback.id)).where(
                DataAgentFeedback.tenant_id == scope.tenant_id,
                DataAgentFeedback.workspace_id == scope.workspace_id,
                DataAgentFeedback.status == "open",
                DataAgentFeedback.run_id.in_(
                    select(DataAgentRunRecord.id).where(
                        DataAgentRunRecord.tenant_id == scope.tenant_id,
                        DataAgentRunRecord.workspace_id == scope.workspace_id,
                        DataAgentRunRecord.data_source_id == data_source_id,
                    )
                ),
            )
        )
        or 0
    )
    open_failures = int(
        await db.scalar(
            select(func.count(DataAgentFailurePattern.id)).where(
                DataAgentFailurePattern.tenant_id == scope.tenant_id,
                DataAgentFailurePattern.workspace_id == scope.workspace_id,
                DataAgentFailurePattern.data_source_id == data_source_id,
                DataAgentFailurePattern.status == "open",
            )
        )
        or 0
    )
    learning_counts = dict(
        (
            await db.execute(
                select(DataAgentLearningPattern.status, func.count(DataAgentLearningPattern.id))
                .where(
                    DataAgentLearningPattern.tenant_id == scope.tenant_id,
                    DataAgentLearningPattern.workspace_id == scope.workspace_id,
                    DataAgentLearningPattern.data_source_id == data_source_id,
                )
                .group_by(DataAgentLearningPattern.status)
            )
        ).all()
    )
    golden_counts = dict(
        (
            await db.execute(
                select(DataAgentEvaluationCase.status, func.count(DataAgentEvaluationCase.id))
                .where(
                    DataAgentEvaluationCase.tenant_id == scope.tenant_id,
                    DataAgentEvaluationCase.workspace_id == scope.workspace_id,
                    DataAgentEvaluationCase.data_source_id == data_source_id,
                )
                .group_by(DataAgentEvaluationCase.status)
            )
        ).all()
    )
    last_suite = await db.scalar(
        select(DataAgentEvaluationSuiteRun)
        .where(
            DataAgentEvaluationSuiteRun.tenant_id == scope.tenant_id,
            DataAgentEvaluationSuiteRun.workspace_id == scope.workspace_id,
            DataAgentEvaluationSuiteRun.data_source_id == data_source_id,
        )
        .order_by(DataAgentEvaluationSuiteRun.started_at.desc())
    )
    sorted_durations = sorted(durations)
    p95_index = max(
        0,
        min(len(sorted_durations) - 1, math.ceil(len(sorted_durations) * 0.95) - 1),
    )
    return {
        "window_days": days,
        "runs": {
            "total": total_runs,
            "analyzed": len(run_rows),
            "truncated": total_runs > len(run_rows),
            "completed": completed,
            "verified": verified,
            "success_rate": round(completed / len(run_rows), 4) if run_rows else None,
            "verified_answer_rate": round(verified / len(run_rows), 4) if run_rows else None,
            "evidence_complete_rate": (
                round(evidence_complete / len(run_rows), 4) if run_rows else None
            ),
            "p95_execution_ms": sorted_durations[p95_index] if sorted_durations else None,
            "states": state_counts,
            "failure_stages": dict(
                sorted(failure_stages.items(), key=lambda item: (-item[1], item[0]))[:10]
            ),
        },
        "governance": {
            "open_feedback": open_feedback,
            "open_failure_patterns": open_failures,
            "learning": learning_counts,
            "golden_cases": golden_counts,
        },
        "release_gate": _evaluation_suite_payload(last_suite) if last_suite else None,
    }


@router.get("/data-agent/governance/failure-patterns")
async def list_failure_patterns(
    request: Request,
    data_source_id: str = Query(..., min_length=1),
    status: str = Query(default="open", pattern="^(open|resolved|ignored|all)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_data_governance_admin(current_user)
    scope, _ = await _source_for_scope(request, current_user, db, data_source_id, "view")
    statement = select(DataAgentFailurePattern).where(
        DataAgentFailurePattern.tenant_id == scope.tenant_id,
        DataAgentFailurePattern.workspace_id == scope.workspace_id,
        DataAgentFailurePattern.data_source_id == data_source_id,
    )
    if status != "all":
        statement = statement.where(DataAgentFailurePattern.status == status)
    rows = list(
        (
            await db.execute(
                statement.order_by(DataAgentFailurePattern.last_failure_at.desc()).limit(200)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_failure_pattern_payload(row) for row in rows], "total": len(rows)}


@router.post("/data-agent/governance/failure-patterns/{pattern_id}/resolve")
async def resolve_failure_pattern(
    request: Request,
    pattern_id: str,
    payload: GovernanceResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_data_governance_admin(current_user)
    tenant = build_tenant_metadata(request, user_id=current_user.id)
    row = await db.scalar(
        select(DataAgentFailurePattern).where(
            DataAgentFailurePattern.id == pattern_id,
            DataAgentFailurePattern.tenant_id == str(tenant.get("tenant_id") or "default"),
            DataAgentFailurePattern.workspace_id == str(tenant.get("workspace_id") or "default"),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="failure pattern not found")
    await _source_for_scope(request, current_user, db, row.data_source_id, "edit")
    row.status = payload.status
    row.resolution_note = payload.resolution_note
    row.resolved_by = current_user.id
    row.resolved_at = datetime.now(UTC)
    await db.commit()
    return {"item": _failure_pattern_payload(row)}


@router.get("/data-agent/governance/feedback")
async def list_data_agent_feedback(
    request: Request,
    data_source_id: str = Query(..., min_length=1),
    status: str = Query(default="open", pattern="^(open|resolved|ignored|all)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_data_governance_admin(current_user)
    scope, _ = await _source_for_scope(request, current_user, db, data_source_id, "view")
    statement = (
        select(DataAgentFeedback)
        .join(DataAgentRunRecord, DataAgentRunRecord.id == DataAgentFeedback.run_id)
        .where(
            DataAgentFeedback.tenant_id == scope.tenant_id,
            DataAgentFeedback.workspace_id == scope.workspace_id,
            DataAgentRunRecord.data_source_id == data_source_id,
        )
    )
    if status != "all":
        statement = statement.where(DataAgentFeedback.status == status)
    rows = list(
        (await db.execute(statement.order_by(DataAgentFeedback.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return {"items": [_feedback_payload(row) for row in rows], "total": len(rows)}


@router.post("/data-agent/governance/feedback/{feedback_id}/resolve")
async def resolve_data_agent_feedback(
    request: Request,
    feedback_id: str,
    payload: GovernanceResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_data_governance_admin(current_user)
    tenant = build_tenant_metadata(request, user_id=current_user.id)
    row = await db.scalar(
        select(DataAgentFeedback).where(
            DataAgentFeedback.id == feedback_id,
            DataAgentFeedback.tenant_id == str(tenant.get("tenant_id") or "default"),
            DataAgentFeedback.workspace_id == str(tenant.get("workspace_id") or "default"),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="feedback not found")
    run = await db.get(DataAgentRunRecord, row.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="DataAgent run not found")
    await _source_for_scope(request, current_user, db, run.data_source_id, "edit")
    row.status = payload.status
    row.resolution_note = payload.resolution_note
    row.resolved_by = current_user.id
    row.resolved_at = datetime.now(UTC)
    await db.commit()
    return {"item": _feedback_payload(row)}


def _semantic_asset_payload(asset: DataAgentSemanticAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "data_source_id": asset.data_source_id,
        "asset_type": asset.asset_type,
        "asset_key": asset.asset_key,
        "version": asset.version,
        "status": asset.status,
        "authority": asset.authority,
        "title": asset.title,
        "description": asset.description,
        "definition": asset.definition_json or {},
        "source_refs": asset.source_refs or [],
        "business_domain": asset.business_domain,
        "owner": asset.owner,
        "valid_from": asset.valid_from,
        "valid_to": asset.valid_to,
        "approved_by": asset.approved_by,
        "approved_at": asset.approved_at,
    }


@router.post("/data-agent/profiles/refresh")
async def refresh_data_profiles(
    request: Request,
    payload: ProfileRefreshRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not settings.data_agent_profile_enabled:
        raise HTTPException(status_code=404, detail="DataAgent 数据画像未启用")
    scope, source = await _source_for_scope(
        request, current_user, db, payload.data_source_id, "query"
    )
    profiles = await DataProfiler(db, source).refresh(
        user_id=current_user.id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        requested_tables=payload.tables or None,
    )
    await db.commit()
    return {
        "data_source_id": payload.data_source_id,
        "profile_count": len(profiles),
        "failed_count": sum(1 for profile in profiles if profile.status == "failed"),
        "items": [serialize_profile(profile) for profile in profiles],
    }


@router.get("/data-agent/profiles")
async def list_data_profiles(
    request: Request,
    data_source_id: str = Query(..., min_length=1),
    table_name: str | None = Query(default=None, max_length=255),
    status: str = Query(default="current", max_length=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope, _ = await _source_for_scope(request, current_user, db, data_source_id, "query")
    statement = select(DataAgentProfile).where(
        DataAgentProfile.user_id == scope.user_id,
        DataAgentProfile.tenant_id == scope.tenant_id,
        DataAgentProfile.workspace_id == scope.workspace_id,
        DataAgentProfile.data_source_id == data_source_id,
    )
    if table_name:
        statement = statement.where(DataAgentProfile.table_name == table_name)
    if status:
        statement = statement.where(DataAgentProfile.status == status)
    rows = list(
        (await db.execute(statement.order_by(DataAgentProfile.profiled_at.desc()).limit(5000)))
        .scalars()
        .all()
    )
    return {"items": [serialize_profile(row) for row in rows], "total": len(rows)}


@router.post("/data-agent/evaluation-cases/{case_id}/evaluate")
async def evaluate_case(
    request: Request,
    case_id: str,
    payload: EvaluationRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _validate_max_rows(payload.max_rows)
    tenant = build_tenant_metadata(request, user_id=current_user.id)
    case = await db.scalar(
        select(DataAgentEvaluationCase).where(
            DataAgentEvaluationCase.id == case_id,
            DataAgentEvaluationCase.tenant_id == str(tenant.get("tenant_id") or "default"),
            DataAgentEvaluationCase.workspace_id == str(tenant.get("workspace_id") or "default"),
        )
    )
    if case is None:
        raise HTTPException(status_code=404, detail="evaluation case not found")
    scope, source = await _source_for_scope(
        request, current_user, db, case.data_source_id, "query" if payload.execute else "view"
    )
    evaluation_service = _service(db, source, learning_enabled=False)
    run = await evaluation_service.create(
        QueryRequest(
            question=case.question,
            scope=scope,
            run_purpose="evaluation",
            mode=ExecutionMode.SQL_ONLY,
            candidate_count=3,
            max_rows=payload.max_rows,
            source_decision=DataSourceDecision(
                status="selected",
                question=case.question,
                selected_data_source_id=source.id,
                selected_data_source_name=source.name,
                confidence=1.0,
                reason="Golden Case 已冻结到当前治理数据源",
            ),
        )
    )
    if payload.execute and run.selected_candidate_id:
        run = await evaluation_service.execute(
            run.id,
            scope,
            candidate_id=run.selected_candidate_id,
            confirmed=True,
        )
    selected = run.selected_candidate()
    plan_comparison = (
        PlanComparator().compare(
            case.expected_plan,
            run.logical_plan.model_dump(mode="json") if run.logical_plan else {},
        )
        if case.expected_plan
        else None
    )
    sql_matches = False if case.expected_sql else None
    if case.expected_sql and selected and run.evidence:
        sql_matches = sql_structure_hash(
            case.expected_sql, dialect=run.evidence.dialect
        ) == sql_structure_hash(selected.sql, dialect=run.evidence.dialect)
    result_comparison = None
    if payload.execute and run.result is not None and case.expected_result:
        result_comparison = ResultComparator().compare(case.expected_result, run.result.rows)
    schema_matches = bool(
        not case.schema_fingerprint
        or run.evidence
        and run.evidence.schema_fingerprint == case.schema_fingerprint
    )
    evidence_coverage = dict(run.answer_metadata.get("evidence_requirements") or {})
    evidence_complete = bool(evidence_coverage) and all(evidence_coverage.values())
    passed = all(
        check
        for check in (
            schema_matches,
            plan_comparison.matches if plan_comparison is not None else True,
            sql_matches if sql_matches is not None else True,
            (
                result_comparison.exact
                if result_comparison is not None
                else not (payload.execute and bool(case.expected_result))
            ),
            run.state.value == "completed" if payload.execute else True,
            evidence_complete if payload.execute else True,
        )
    )
    evaluation = {
        "passed": passed,
        "plan_comparison": plan_comparison.__dict__ if plan_comparison else None,
        "sql_structure_matches": sql_matches,
        "result_comparison": (
            result_comparison.__dict__ if result_comparison is not None else None
        ),
        "schema_matches": schema_matches,
        "schema_fingerprint": run.evidence.schema_fingerprint if run.evidence else None,
        "semantic_version": run.evidence.semantic_version if run.evidence else None,
        "evidence_complete": evidence_complete if payload.execute else None,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    case.last_evaluation_json = evaluation
    case.last_run_id = run.id
    case.last_evaluated_at = datetime.now(UTC)
    if passed:
        case.pass_count += 1
    else:
        case.failure_count += 1
    await db.commit()
    return {
        "case": _evaluation_case_payload(case),
        "run": _payload(run),
        "sql_available": bool(selected and selected.sql),
        "evaluation": evaluation,
    }


@router.post("/data-agent/evaluation-suites/run")
async def run_evaluation_suite(
    request: Request,
    payload: EvaluationSuiteRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """串行运行已发布 Golden Case，并持久化可作为发布门禁的套件结果。"""

    _ensure_data_governance_admin(current_user)
    _validate_max_rows(payload.max_rows)
    scope, source = await _source_for_scope(
        request,
        current_user,
        db,
        payload.data_source_id,
        "query" if payload.execute else "view",
    )
    statement = select(DataAgentEvaluationCase).where(
        DataAgentEvaluationCase.tenant_id == scope.tenant_id,
        DataAgentEvaluationCase.workspace_id == scope.workspace_id,
        DataAgentEvaluationCase.data_source_id == payload.data_source_id,
        DataAgentEvaluationCase.status == "published",
    )
    if payload.business_domain:
        statement = statement.where(
            DataAgentEvaluationCase.business_domain == payload.business_domain
        )
    cases = list(
        (await db.execute(statement.order_by(DataAgentEvaluationCase.created_at.asc())))
        .scalars()
        .all()
    )
    if payload.tags:
        required_tags = set(payload.tags)
        cases = [case for case in cases if required_tags.issubset(set(case.tags or []))]
    if not cases:
        raise HTTPException(status_code=409, detail="没有符合条件的已发布 Golden Case")

    suite = DataAgentEvaluationSuiteRun(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        data_source_id=payload.data_source_id,
        name=payload.name,
        execute=payload.execute,
        tags_json=payload.tags,
        business_domain=payload.business_domain,
        minimum_pass_rate=payload.minimum_pass_rate,
        case_count=len(cases),
        status="running",
    )
    db.add(suite)
    await db.flush()

    results: list[dict[str, Any]] = []
    for case in cases:
        evaluation_service = _service(db, source, learning_enabled=False)
        run = await evaluation_service.create(
            QueryRequest(
                question=case.question,
                scope=scope,
                run_purpose="evaluation",
                mode=ExecutionMode.SQL_ONLY,
                candidate_count=3,
                max_rows=payload.max_rows,
                idempotency_key=f"evaluation-suite:{suite.id}:{case.id}",
                source_decision=DataSourceDecision(
                    status="selected",
                    question=case.question,
                    selected_data_source_id=source.id,
                    selected_data_source_name=source.name,
                    confidence=1.0,
                    reason="Golden Case 已冻结到当前治理数据源",
                ),
            )
        )
        if payload.execute and run.selected_candidate_id:
            run = await evaluation_service.execute(
                run.id,
                scope,
                candidate_id=run.selected_candidate_id,
                confirmed=True,
            )
        selected = run.selected_candidate()
        plan_comparison = (
            PlanComparator().compare(
                case.expected_plan,
                run.logical_plan.model_dump(mode="json") if run.logical_plan else {},
            )
            if case.expected_plan
            else None
        )
        sql_matches = False if case.expected_sql else None
        if case.expected_sql and selected and run.evidence:
            sql_matches = sql_structure_hash(
                case.expected_sql, dialect=run.evidence.dialect
            ) == sql_structure_hash(selected.sql, dialect=run.evidence.dialect)
        result_comparison = None
        if payload.execute and run.result is not None and case.expected_result:
            result_comparison = ResultComparator().compare(case.expected_result, run.result.rows)
        schema_matches = bool(
            not case.schema_fingerprint
            or run.evidence
            and run.evidence.schema_fingerprint == case.schema_fingerprint
        )
        evidence_coverage = dict(run.answer_metadata.get("evidence_requirements") or {})
        evidence_complete = bool(evidence_coverage) and all(evidence_coverage.values())
        passed = all(
            check
            for check in (
                schema_matches,
                plan_comparison.matches if plan_comparison else True,
                sql_matches if sql_matches is not None else True,
                (
                    result_comparison.exact
                    if result_comparison
                    else not (payload.execute and bool(case.expected_result))
                ),
                run.state.value == "completed" if payload.execute else True,
                evidence_complete if payload.execute else True,
            )
        )
        item = {
            "case_id": case.id,
            "run_id": run.id,
            "question": case.question,
            "passed": passed,
            "schema_matches": schema_matches,
            "plan_matches": plan_comparison.matches if plan_comparison else None,
            "missing_plan_paths": plan_comparison.missing_paths if plan_comparison else [],
            "sql_structure_matches": sql_matches,
            "result_exact": result_comparison.exact if result_comparison else None,
            "run_state": run.state.value,
            "evidence_complete": evidence_complete if payload.execute else None,
        }
        results.append(item)
        case.last_evaluation_json = {**item, "evaluated_at": datetime.now(UTC).isoformat()}
        case.last_run_id = run.id
        case.last_evaluated_at = datetime.now(UTC)
        if passed:
            case.pass_count += 1
        else:
            case.failure_count += 1

    suite.passed_count = sum(1 for item in results if item["passed"])
    suite.failed_count = len(results) - suite.passed_count
    suite.pass_rate = suite.passed_count / max(1, len(results))
    suite.status = "passed" if suite.pass_rate >= suite.minimum_pass_rate else "failed"
    suite.results_json = results
    suite.completed_at = datetime.now(UTC)
    await db.commit()
    return {"suite": _evaluation_suite_payload(suite), "results": results}


@router.get("/data-agent/evaluation-suites")
async def list_evaluation_suites(
    request: Request,
    data_source_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ensure_data_governance_admin(current_user)
    scope, _ = await _source_for_scope(request, current_user, db, data_source_id, "view")
    rows = list(
        (
            await db.execute(
                select(DataAgentEvaluationSuiteRun)
                .where(
                    DataAgentEvaluationSuiteRun.tenant_id == scope.tenant_id,
                    DataAgentEvaluationSuiteRun.workspace_id == scope.workspace_id,
                    DataAgentEvaluationSuiteRun.data_source_id == data_source_id,
                )
                .order_by(DataAgentEvaluationSuiteRun.started_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_evaluation_suite_payload(row) for row in rows], "total": len(rows)}


def _evaluation_case_payload(case: DataAgentEvaluationCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "data_source_id": case.data_source_id,
        "question": case.question,
        "expected_sql": case.expected_sql,
        "expected_plan": case.expected_plan or {},
        "expected_result": case.expected_result or [],
        "schema_fingerprint": case.schema_fingerprint,
        "tags": case.tags or [],
        "business_domain": case.business_domain,
        "status": case.status,
        "published_by": case.published_by,
        "published_at": case.published_at,
        "last_evaluation": case.last_evaluation_json or {},
        "pass_count": case.pass_count,
        "failure_count": case.failure_count,
        "last_evaluated_at": case.last_evaluated_at,
    }


def _evaluation_suite_payload(suite: DataAgentEvaluationSuiteRun) -> dict[str, Any]:
    return {
        "id": suite.id,
        "name": suite.name,
        "data_source_id": suite.data_source_id,
        "execute": suite.execute,
        "tags": suite.tags_json or [],
        "business_domain": suite.business_domain,
        "minimum_pass_rate": suite.minimum_pass_rate,
        "case_count": suite.case_count,
        "passed_count": suite.passed_count,
        "failed_count": suite.failed_count,
        "pass_rate": suite.pass_rate,
        "status": suite.status,
        "started_at": suite.started_at,
        "completed_at": suite.completed_at,
    }


def _failure_pattern_payload(row: DataAgentFailurePattern) -> dict[str, Any]:
    return {
        "id": row.id,
        "data_source_id": row.data_source_id,
        "pattern_key": row.pattern_key,
        "schema_fingerprint": row.schema_fingerprint,
        "semantic_version": row.semantic_version,
        "failure_stage": row.failure_stage,
        "error_codes": row.error_codes or [],
        "question_examples": row.question_examples or [],
        "candidate_sql_hash": row.candidate_sql_hash,
        "failure_count": row.failure_count,
        "status": row.status,
        "resolution_note": row.resolution_note,
        "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at,
        "last_run_id": row.last_run_id,
        "last_failure_at": row.last_failure_at,
    }


def _feedback_payload(row: DataAgentFeedback) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "verdict": row.verdict,
        "candidate_id": row.candidate_id,
        "corrected_sql": row.corrected_sql,
        "comment": row.comment,
        "metadata": row.metadata_json or {},
        "status": row.status,
        "resolution_note": row.resolution_note,
        "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at,
        "created_at": row.created_at,
    }
