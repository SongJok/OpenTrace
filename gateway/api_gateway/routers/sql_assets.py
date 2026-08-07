"""数据库 SQL 资产、查询草案与显式确认执行 API。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes, ValidationException
from infra.metadata.schema_inspector import load_schema_inspection
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import Project, SQLAsset, SQLAssetSource, SQLQueryDraft, User
from kernel.data_cognition.sql_dialect import detect_sql_dialect
from services.sql_assets import (
    MAX_UPLOAD_BYTES,
    create_sql_asset_source,
    execute_sql_query_draft,
    load_scoped_draft,
    schema_fingerprint,
    serialize_asset,
    serialize_draft,
    serialize_source,
)

router = APIRouter()


class SQLAssetUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(draft|published|deprecated|rejected)$")


class SQLDraftExecuteRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list, max_length=5)
    execute_all: bool = False


def _scope(request: Request, current_user: User) -> tuple[dict, str, str]:
    metadata = build_tenant_metadata(request, user_id=current_user.id)
    tenant_id = str(metadata.get("tenant_id") or "default")
    workspace_id = str(metadata.get("workspace_id") or "default")
    return metadata, tenant_id, workspace_id


async def _source_or_404(
    db: AsyncSession,
    *,
    request: Request,
    current_user: User,
    database_id: str,
    permission: str,
):
    metadata, _, _ = _scope(request, current_user)
    source = await get_accessible_data_source(
        db,
        user_id=current_user.id,
        tenant_metadata=metadata,
        data_source_id=database_id,
        required_permission=permission,
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="数据源不存在")
    return source


async def _validate_project(
    db: AsyncSession,
    *,
    project_id: str | None,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    data_source_id: str,
) -> None:
    if not project_id:
        return
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
            Project.tenant_id == tenant_id,
            Project.workspace_id == workspace_id,
            Project.archived_at.is_(None),
        )
    )
    if project is None or data_source_id not in set(project.data_source_ids or []):
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="Project 未绑定该数据源")


@router.post("/databases/{database_id}/sql-assets/upload")
async def upload_sql_asset(
    request: Request,
    database_id: str,
    file: UploadFile = File(...),
    dialect: str | None = Form(default=None),
    project_id: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    source = await _source_or_404(
        db,
        request=request,
        current_user=current_user,
        database_id=database_id,
        permission="edit",
    )
    _, tenant_id, workspace_id = _scope(request, current_user)
    await _validate_project(
        db,
        project_id=project_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=database_id,
    )
    filename = str(file.filename or "").strip()
    if not filename.lower().endswith((".sql", ".txt")):
        raise ValidationException("仅支持上传 .sql 或 .txt 文件")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValidationException("SQL 文件不能超过 2 MB")
    try:
        source_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationException("SQL 文件必须使用 UTF-8 编码") from exc
    expected_dialect = detect_sql_dialect(source.source_type).name
    if dialect and detect_sql_dialect(dialect).name != expected_dialect:
        raise ValidationException("SQL 方言必须与数据源类型一致")
    asset_source, assets, deduplicated = await create_sql_asset_source(
        db,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=database_id,
        filename=filename,
        content_type=file.content_type or "text/plain",
        source_text=source_text,
        dialect=expected_dialect,
        project_id=project_id,
    )
    return {
        "source": serialize_source(asset_source),
        "assets": [serialize_asset(item) for item in assets],
        "deduplicated": deduplicated,
        "executed": False,
    }


@router.get("/databases/{database_id}/sql-assets")
async def list_sql_assets(
    request: Request,
    database_id: str,
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _source_or_404(
        db,
        request=request,
        current_user=current_user,
        database_id=database_id,
        permission="view",
    )
    _, tenant_id, workspace_id = _scope(request, current_user)
    source_stmt = (
        select(SQLAssetSource)
        .where(
            SQLAssetSource.tenant_id == tenant_id,
            SQLAssetSource.workspace_id == workspace_id,
            SQLAssetSource.data_source_id == database_id,
        )
        .order_by(SQLAssetSource.created_at.desc())
    )
    asset_stmt = select(SQLAsset).where(
        SQLAsset.tenant_id == tenant_id,
        SQLAsset.workspace_id == workspace_id,
        SQLAsset.data_source_id == database_id,
    )
    if status:
        asset_stmt = asset_stmt.where(SQLAsset.status == status)
    asset_stmt = asset_stmt.order_by(SQLAsset.created_at.desc(), SQLAsset.statement_index)
    sources = list((await db.execute(source_stmt)).scalars().all())
    assets = list((await db.execute(asset_stmt)).scalars().all())
    return {
        "sources": [serialize_source(item) for item in sources],
        "assets": [serialize_asset(item) for item in assets],
    }


@router.patch("/databases/{database_id}/sql-assets/{asset_id}")
async def update_sql_asset(
    request: Request,
    database_id: str,
    asset_id: str,
    payload: SQLAssetUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _source_or_404(
        db,
        request=request,
        current_user=current_user,
        database_id=database_id,
        permission="edit",
    )
    _, tenant_id, workspace_id = _scope(request, current_user)
    asset = await db.scalar(
        select(SQLAsset).where(
            SQLAsset.id == asset_id,
            SQLAsset.tenant_id == tenant_id,
            SQLAsset.workspace_id == workspace_id,
            SQLAsset.data_source_id == database_id,
        )
    )
    if asset is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="SQL 资产不存在")
    if payload.status == "published":
        if not asset.executable or (asset.validation_report or {}).get("status") != "pass":
            raise ValidationException("只有通过安全校验的只读 SQL 才能发布")
        inspection = await load_schema_inspection(db, database_id)
        if asset.schema_fingerprint != schema_fingerprint(inspection.schema_payload):
            raise ValidationException("数据源 Schema 已变化，请重新上传并审核该 SQL")
        asset.approved_by = current_user.id
        asset.approved_at = datetime.now(UTC)
    if payload.title is not None:
        asset.title = payload.title.strip()
    if payload.description is not None:
        asset.description = payload.description.strip()
    if payload.tags is not None:
        asset.tags = sorted({item.strip() for item in payload.tags if item.strip()})[:30]
    if payload.status is not None:
        asset.status = payload.status
    await db.commit()
    return serialize_asset(asset)


@router.delete("/databases/{database_id}/sql-assets/sources/{source_id}", status_code=204)
async def delete_sql_asset_source(
    request: Request,
    database_id: str,
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _source_or_404(
        db,
        request=request,
        current_user=current_user,
        database_id=database_id,
        permission="edit",
    )
    _, tenant_id, workspace_id = _scope(request, current_user)
    result = await db.execute(
        delete(SQLAssetSource).where(
            SQLAssetSource.id == source_id,
            SQLAssetSource.tenant_id == tenant_id,
            SQLAssetSource.workspace_id == workspace_id,
            SQLAssetSource.data_source_id == database_id,
        )
    )
    if not result.rowcount:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="SQL 资产源文件不存在")
    await db.commit()


@router.get("/databases/{database_id}/sql-drafts")
async def list_sql_drafts(
    request: Request,
    database_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _source_or_404(
        db,
        request=request,
        current_user=current_user,
        database_id=database_id,
        permission="query",
    )
    _, tenant_id, workspace_id = _scope(request, current_user)
    drafts = list(
        (
            await db.execute(
                select(SQLQueryDraft)
                .where(
                    SQLQueryDraft.user_id == current_user.id,
                    SQLQueryDraft.tenant_id == tenant_id,
                    SQLQueryDraft.workspace_id == workspace_id,
                    SQLQueryDraft.data_source_id == database_id,
                )
                .order_by(SQLQueryDraft.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": item.id,
                "question": item.question,
                "group_type": item.group_type,
                "status": item.status,
                "created_at": item.created_at,
            }
            for item in drafts
        ]
    }


@router.get("/databases/{database_id}/sql-drafts/{draft_id}")
async def get_sql_draft(
    request: Request,
    database_id: str,
    draft_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _source_or_404(
        db,
        request=request,
        current_user=current_user,
        database_id=database_id,
        permission="query",
    )
    _, tenant_id, workspace_id = _scope(request, current_user)
    draft, candidates = await load_scoped_draft(
        db,
        draft_id=draft_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if draft.data_source_id != database_id:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="SQL 查询草案不存在")
    return serialize_draft(draft, candidates)


@router.post("/databases/{database_id}/sql-drafts/{draft_id}/execute")
async def execute_sql_draft(
    request: Request,
    database_id: str,
    draft_id: str,
    payload: SQLDraftExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _source_or_404(
        db,
        request=request,
        current_user=current_user,
        database_id=database_id,
        permission="query",
    )
    _, tenant_id, workspace_id = _scope(request, current_user)
    draft, _ = await load_scoped_draft(
        db,
        draft_id=draft_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if draft.data_source_id != database_id:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="SQL 查询草案不存在")
    return await execute_sql_query_draft(
        db,
        draft_id=draft_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        candidate_ids=payload.candidate_ids,
        execute_all=payload.execute_all,
    )
