"""独立 Text2SQL 平台的 OpenTrace 适配 API。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.config.settings import settings
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import Project, User
from infra.storage.text2sql_models import (
    Text2SQLEvaluationCase,
    Text2SQLFeedback,
    Text2SQLSemanticAsset,
)
from text2sql.adapters.opentrace.answer import OpenTraceAnswerSynthesizer
from text2sql.adapters.opentrace.evidence import OpenTraceEvidenceProvider
from text2sql.adapters.opentrace.executor import OpenTraceQueryExecutor
from text2sql.adapters.opentrace.generator import OpenTraceSQLGenerator
from text2sql.adapters.opentrace.repository import OpenTraceRunRepository
from text2sql.contracts import DataScope, ExecutionMode, QueryRequest, deterministic_run_id
from text2sql.service import Text2SQLService


def _ensure_enabled() -> None:
    if not settings.text2sql_enabled:
        raise HTTPException(status_code=404, detail="Text2SQL 未启用")


router = APIRouter(dependencies=[Depends(_ensure_enabled)])


class Text2SQLQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8192)
    data_source_id: str = Field(..., min_length=1, max_length=128)
    mode: str = Field(default="sql_only", pattern="^(sql_only|execute_and_answer)$")
    confirmed: bool = False
    clarification_context: str | None = Field(default=None, max_length=4000)
    candidate_count: int = Field(default=3, ge=1, le=5)
    max_rows: int = Field(default=100, ge=1, le=10000)
    requested_tables: list[str] = Field(default_factory=list, max_length=100)
    requested_output: str | None = Field(default=None, max_length=1000)
    project_id: str | None = Field(default=None, max_length=128)


class Text2SQLExecuteRequest(BaseModel):
    candidate_id: str | None = Field(default=None, max_length=64)
    confirmed: bool = True


class SemanticAssetCreateRequest(BaseModel):
    data_source_id: str = Field(..., min_length=1, max_length=128)
    asset_type: str = Field(
        ..., pattern="^(business_process|data_quality|entity|dimension|source_policy)$"
    )
    asset_key: str = Field(..., min_length=1, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    definition: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list, max_length=50)
    project_id: str | None = Field(default=None, max_length=128)


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


def _scope(
    request: Request, user: User, data_source_id: str, project_id: str | None = None
) -> DataScope:
    metadata = build_tenant_metadata(request, user_id=user.id)
    return DataScope(
        user_id=user.id,
        tenant_id=str(metadata.get("tenant_id") or "default"),
        workspace_id=str(metadata.get("workspace_id") or "default"),
        data_source_id=data_source_id,
        project_id=project_id,
    )


def _service(db: AsyncSession, source: Any) -> Text2SQLService:
    return Text2SQLService(
        evidence_provider=OpenTraceEvidenceProvider(db, source),
        sql_generator=OpenTraceSQLGenerator(),
        query_executor=OpenTraceQueryExecutor(source),
        answer_synthesizer=OpenTraceAnswerSynthesizer(),
        repository=OpenTraceRunRepository(db),
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


async def _validate_project_scope(
    db: AsyncSession,
    *,
    scope: DataScope,
    project_id: str | None,
) -> None:
    if not project_id:
        return
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == scope.user_id,
            Project.tenant_id == scope.tenant_id,
            Project.workspace_id == scope.workspace_id,
            Project.archived_at.is_(None),
        )
    )
    if project is None or scope.data_source_id not in set(project.data_source_ids or []):
        raise HTTPException(status_code=403, detail="Project 未绑定该数据源")


def _validate_max_rows(max_rows: int) -> None:
    if max_rows > settings.text2sql_max_result_rows:
        raise HTTPException(
            status_code=422,
            detail=f"max_rows 不能超过平台上限 {settings.text2sql_max_result_rows}",
        )


@router.post("/text2sql/queries")
async def create_text2sql_query(
    request: Request,
    payload: Text2SQLQueryRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, payload.data_source_id, payload.project_id)
    await _validate_project_scope(db, scope=scope, project_id=payload.project_id)
    _validate_max_rows(payload.max_rows)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
        data_source_id=scope.data_source_id,
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
        idempotency_key=normalized_idempotency_key,
    )
    if normalized_idempotency_key:
        existing = await OpenTraceRunRepository(db).get(deterministic_run_id(query), scope)
        if existing is not None:
            if existing.request != query:
                raise HTTPException(status_code=409, detail="Idempotency-Key 已用于不同请求")
            return _payload(existing)
    run = await _service(db, source).create(query)
    return _payload(run)


@router.get("/text2sql/queries/{run_id}")
async def get_text2sql_query(
    request: Request,
    run_id: str,
    data_source_id: str,
    project_id: str | None = Query(default=None, max_length=128),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, data_source_id, project_id)
    await _validate_project_scope(db, scope=scope, project_id=project_id)
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
        raise HTTPException(status_code=404, detail="text2sql run not found")
    return _payload(run)


@router.post("/text2sql/queries/{run_id}/execute")
async def execute_text2sql_query(
    request: Request,
    run_id: str,
    payload: Text2SQLExecuteRequest,
    data_source_id: str,
    project_id: str | None = Query(default=None, max_length=128),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, data_source_id, project_id)
    await _validate_project_scope(db, scope=scope, project_id=project_id)
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


@router.post("/text2sql/semantic-assets")
async def create_semantic_asset(
    request: Request,
    payload: SemanticAssetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope, _ = await _source_for_scope(request, current_user, db, payload.data_source_id, "edit")
    await _validate_project_scope(db, scope=scope, project_id=payload.project_id)
    asset = Text2SQLSemanticAsset(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        project_id=payload.project_id,
        data_source_id=payload.data_source_id,
        asset_type=payload.asset_type,
        asset_key=payload.asset_key,
        title=payload.title,
        description=payload.description,
        definition_json=payload.definition,
        source_refs=payload.source_refs,
        authority="contextual",
        status="draft",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return {"asset": _semantic_asset_payload(asset)}


@router.get("/text2sql/semantic-assets")
async def list_semantic_assets(
    request: Request,
    data_source_id: str = Query(..., min_length=1),
    project_id: str | None = Query(default=None, max_length=128),
    asset_type: str | None = Query(default=None),
    status: str = Query(default="published"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, data_source_id, project_id)
    await _validate_project_scope(db, scope=scope, project_id=project_id)
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
    statement = select(Text2SQLSemanticAsset).where(
        Text2SQLSemanticAsset.tenant_id == scope.tenant_id,
        Text2SQLSemanticAsset.workspace_id == scope.workspace_id,
        Text2SQLSemanticAsset.data_source_id == data_source_id,
        or_(
            Text2SQLSemanticAsset.project_id.is_(None),
            Text2SQLSemanticAsset.project_id == scope.project_id,
        ),
    )
    if asset_type:
        statement = statement.where(Text2SQLSemanticAsset.asset_type == asset_type)
    if status:
        statement = statement.where(Text2SQLSemanticAsset.status == status)
    rows = list(
        (await db.execute(statement.order_by(Text2SQLSemanticAsset.updated_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return {"items": [_semantic_asset_payload(row) for row in rows], "total": len(rows)}


@router.post("/text2sql/semantic-assets/{asset_id}/publish")
async def publish_semantic_asset(
    request: Request,
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    asset = await db.scalar(
        select(Text2SQLSemanticAsset).where(
            Text2SQLSemanticAsset.id == asset_id,
            Text2SQLSemanticAsset.tenant_id
            == str(
                build_tenant_metadata(request, user_id=current_user.id).get("tenant_id")
                or "default"
            ),
            Text2SQLSemanticAsset.workspace_id
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
    asset.status = "published"
    asset.authority = "governed"
    asset.approved_by = current_user.id
    asset.approved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(asset)
    return {"asset": _semantic_asset_payload(asset)}


@router.post("/text2sql/evaluation-cases")
async def create_evaluation_case(
    request: Request,
    payload: EvaluationCaseCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope, _ = await _source_for_scope(request, current_user, db, payload.data_source_id, "edit")
    case = Text2SQLEvaluationCase(
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


@router.post("/text2sql/queries/{run_id}/feedback")
async def submit_text2sql_feedback(
    request: Request,
    run_id: str,
    data_source_id: str,
    payload: FeedbackRequest,
    project_id: str | None = Query(default=None, max_length=128),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scope = _scope(request, current_user, data_source_id, project_id)
    await _validate_project_scope(db, scope=scope, project_id=project_id)
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
        raise HTTPException(status_code=404, detail="text2sql run not found")
    feedback = Text2SQLFeedback(
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
    await db.commit()
    return {"feedback_id": feedback.id, "stored": True, "promoted": False}


def _semantic_asset_payload(asset: Text2SQLSemanticAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "data_source_id": asset.data_source_id,
        "project_id": asset.project_id,
        "asset_type": asset.asset_type,
        "asset_key": asset.asset_key,
        "version": asset.version,
        "status": asset.status,
        "authority": asset.authority,
        "title": asset.title,
        "description": asset.description,
        "definition": asset.definition_json or {},
        "source_refs": asset.source_refs or [],
        "approved_by": asset.approved_by,
        "approved_at": asset.approved_at,
    }


def _evaluation_case_payload(case: Text2SQLEvaluationCase) -> dict[str, Any]:
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
    }
