"""独立 DataAgent 平台的 OpenTrace 适配 API。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
from data_agent.contracts import DataScope, ExecutionMode, QueryRequest, deterministic_run_id
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
    DataAgentFeedback,
    DataAgentProfile,
    DataAgentSemanticAsset,
)
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User


def _ensure_enabled() -> None:
    if not settings.data_agent_enabled:
        raise HTTPException(status_code=404, detail="DataAgent 未启用")


router = APIRouter(dependencies=[Depends(_ensure_enabled)])


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


def _service(db: AsyncSession, source: Any) -> DataAgentService:
    return DataAgentService(
        evidence_provider=OpenTraceEvidenceProvider(db, source),
        sql_generator=OpenTraceSQLGenerator(),
        query_executor=OpenTraceQueryExecutor(source),
        answer_synthesizer=OpenTraceAnswerSynthesizer(),
        repository=OpenTraceRunRepository(db),
        learning_repository=(
            OpenTraceLearningRepository(db) if settings.data_agent_learning_enabled else None
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
        status="draft",
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
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
    tenant = build_tenant_metadata(request, user_id=current_user.id)
    case = await db.scalar(
        select(DataAgentEvaluationCase).where(
            DataAgentEvaluationCase.id == case_id,
            DataAgentEvaluationCase.user_id == current_user.id,
            DataAgentEvaluationCase.tenant_id == str(tenant.get("tenant_id") or "default"),
            DataAgentEvaluationCase.workspace_id == str(tenant.get("workspace_id") or "default"),
        )
    )
    if case is None:
        raise HTTPException(status_code=404, detail="evaluation case not found")
    scope, source = await _source_for_scope(
        request, current_user, db, case.data_source_id, "query" if payload.execute else "view"
    )
    run = await _service(db, source).create(
        QueryRequest(
            question=case.question,
            scope=scope,
            mode=ExecutionMode.SQL_ONLY,
            candidate_count=3,
            max_rows=payload.max_rows,
        )
    )
    if payload.execute and run.selected_candidate_id:
        run = await _service(db, source).execute(
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
    sql_matches = None
    if case.expected_sql and selected and run.evidence:
        sql_matches = sql_structure_hash(
            case.expected_sql, dialect=run.evidence.dialect
        ) == sql_structure_hash(selected.sql, dialect=run.evidence.dialect)
    result_comparison = None
    if payload.execute and run.result is not None and case.expected_result:
        result_comparison = ResultComparator().compare(case.expected_result, run.result.rows)
    passed = all(
        check
        for check in (
            plan_comparison.matches if plan_comparison is not None else True,
            sql_matches if sql_matches is not None else True,
            result_comparison.exact if result_comparison is not None else True,
            run.state.value == "completed" if payload.execute else True,
        )
    )
    evaluation = {
        "passed": passed,
        "plan_comparison": plan_comparison.__dict__ if plan_comparison else None,
        "sql_structure_matches": sql_matches,
        "result_comparison": (
            result_comparison.__dict__ if result_comparison is not None else None
        ),
        "schema_fingerprint": run.evidence.schema_fingerprint if run.evidence else None,
        "semantic_version": run.evidence.semantic_version if run.evidence else None,
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
        "status": case.status,
        "last_evaluation": case.last_evaluation_json or {},
        "pass_count": case.pass_count,
        "failure_count": case.failure_count,
        "last_evaluated_at": case.last_evaluated_at,
    }
