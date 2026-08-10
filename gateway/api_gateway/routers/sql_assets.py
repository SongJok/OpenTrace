"""数据库 SQL 资产、查询草案与显式确认执行 API。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.audit.logger import write_audit_log
from infra.errors import AppException, ErrorCodes, ValidationException
from infra.metadata.schema_inspector import load_schema_inspection
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import Project, SQLAsset, SQLAssetSource, SQLQueryDraft, User
from kernel.data_cognition.sql_dialect import detect_sql_dialect
from services.sql_assets import (
    CORPUS_ROLES,
    MAX_BATCH_UPLOAD_BYTES,
    MAX_BATCH_UPLOAD_FILES,
    MAX_UPLOAD_BYTES,
    create_sql_asset_source,
    evaluate_data_source_schema_fingerprint,
    execute_sql_query_draft,
    load_scoped_draft,
    promote_sql_asset_knowledge,
    serialize_asset,
    serialize_draft,
    serialize_source,
    validate_asset_status_transition,
)

router = APIRouter()


class SQLAssetUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=30)
    corpus_role: str | None = Field(default=None, pattern="^(retrieval|evaluation|quarantine)$")
    domain: str | None = Field(default=None, max_length=100)
    owner: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, pattern="^(draft|published|deprecated|rejected)$")
    reason: str | None = Field(default=None, max_length=1000)
    expected_updated_at: datetime | None = None


class SQLDraftExecuteRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list, max_length=5)
    execute_all: bool = False
    retry_failed: bool = False


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
    corpus_role: str = Form(default="retrieval"),
    domain: str | None = Form(default=None),
    owner: str | None = Form(default=None),
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
        corpus_role=corpus_role,
        domain=domain,
        owner=owner,
    )
    await write_audit_log(
        user_id=current_user.id,
        action="sql_asset.upload_deduplicated" if deduplicated else "sql_asset.upload",
        resource_type="sql_asset_source",
        resource_id=asset_source.id,
        payload={
            "data_source_id": database_id,
            "project_id": project_id,
            "filename": filename,
            "statement_count": asset_source.statement_count,
        },
    )
    return {
        "source": serialize_source(asset_source),
        "assets": [serialize_asset(item) for item in assets],
        "deduplicated": deduplicated,
        "executed": False,
    }


@router.post("/databases/{database_id}/sql-assets/batch-upload")
async def batch_upload_sql_assets(
    request: Request,
    database_id: str,
    files: list[UploadFile] = File(...),
    dialect: str | None = Form(default=None),
    project_id: str | None = Form(default=None),
    corpus_role: str = Form(default="retrieval"),
    domain: str | None = Form(default=None),
    owner: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量导入历史 SQL；逐文件返回结果，单个坏文件不会吞掉其余成果。"""

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
    if not files or len(files) > MAX_BATCH_UPLOAD_FILES:
        raise ValidationException(f"每批最多上传 {MAX_BATCH_UPLOAD_FILES} 个 SQL 文件")
    if corpus_role not in CORPUS_ROLES:
        raise ValidationException("非法 SQL 语料分区")
    expected_dialect = detect_sql_dialect(source.source_type).name
    if dialect and detect_sql_dialect(dialect).name != expected_dialect:
        raise ValidationException("SQL 方言必须与数据源类型一致")

    total_bytes = 0
    results: list[dict] = []
    for file in files:
        filename = str(file.filename or "").strip()
        try:
            if not filename.lower().endswith((".sql", ".txt")):
                raise ValidationException("仅支持 .sql 或 .txt 文件")
            raw = await file.read(MAX_UPLOAD_BYTES + 1)
            total_bytes += len(raw)
            if len(raw) > MAX_UPLOAD_BYTES:
                raise ValidationException("单个 SQL 文件不能超过 2 MB")
            if total_bytes > MAX_BATCH_UPLOAD_BYTES:
                raise ValidationException("单批 SQL 文件总大小不能超过 25 MB")
            try:
                source_text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValidationException("SQL 文件必须使用 UTF-8 编码") from exc
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
                corpus_role=corpus_role,
                domain=domain,
                owner=owner,
            )
            results.append(
                {
                    "filename": filename,
                    "status": "deduplicated" if deduplicated else "imported",
                    "source": serialize_source(asset_source),
                    "asset_count": len(assets),
                }
            )
        except (ValidationException, AppException) as exc:
            results.append({"filename": filename, "status": "failed", "error": str(exc)})
        finally:
            await file.close()
    imported = sum(item["status"] == "imported" for item in results)
    deduplicated = sum(item["status"] == "deduplicated" for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    await write_audit_log(
        user_id=current_user.id,
        action="sql_asset.batch_upload",
        resource_type="data_source",
        resource_id=database_id,
        payload={
            "project_id": project_id,
            "corpus_role": corpus_role,
            "file_count": len(files),
            "imported": imported,
            "deduplicated": deduplicated,
            "failed": failed,
        },
    )
    return {
        "results": results,
        "summary": {
            "total": len(results),
            "imported": imported,
            "deduplicated": deduplicated,
            "failed": failed,
        },
        "executed": False,
    }


@router.get("/databases/{database_id}/sql-assets")
async def list_sql_assets(
    request: Request,
    database_id: str,
    status: str | None = Query(
        default=None,
        pattern="^(draft|published|deprecated|rejected)$",
    ),
    project_id: str | None = Query(default=None),
    corpus_role: str | None = Query(default=None, pattern="^(retrieval|evaluation|quarantine)$"),
    quality_status: str | None = Query(
        default=None, pattern="^(unverified|verified|failed|deprecated)$"
    ),
    domain: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
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
    await _validate_project(
        db,
        project_id=project_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=database_id,
    )
    source_conditions = [
        SQLAssetSource.tenant_id == tenant_id,
        SQLAssetSource.workspace_id == workspace_id,
        SQLAssetSource.data_source_id == database_id,
    ]
    asset_conditions = [
        SQLAsset.tenant_id == tenant_id,
        SQLAsset.workspace_id == workspace_id,
        SQLAsset.data_source_id == database_id,
    ]
    if project_id:
        source_conditions.append(
            or_(SQLAssetSource.project_id.is_(None), SQLAssetSource.project_id == project_id)
        )
        asset_conditions.append(
            or_(SQLAsset.project_id.is_(None), SQLAsset.project_id == project_id)
        )
    else:
        source_conditions.append(SQLAssetSource.project_id.is_(None))
        asset_conditions.append(SQLAsset.project_id.is_(None))
    if status:
        asset_conditions.append(SQLAsset.status == status)
    if corpus_role:
        asset_conditions.append(SQLAsset.corpus_role == corpus_role)
    if quality_status:
        asset_conditions.append(SQLAsset.quality_status == quality_status)
    if domain:
        asset_conditions.append(SQLAsset.domain == domain.strip())
    normalized_search = str(search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        asset_conditions.append(
            or_(
                SQLAsset.title.ilike(pattern),
                SQLAsset.description.ilike(pattern),
                SQLAsset.normalized_sql.ilike(pattern),
            )
        )
    source_stmt = (
        select(SQLAssetSource)
        .where(*source_conditions)
        .order_by(SQLAssetSource.created_at.desc())
        .limit(100)
    )
    asset_stmt = (
        select(SQLAsset)
        .where(*asset_conditions)
        .order_by(SQLAsset.created_at.desc(), SQLAsset.statement_index)
        .offset(offset)
        .limit(limit)
    )
    total = int(await db.scalar(select(func.count(SQLAsset.id)).where(*asset_conditions)) or 0)
    sources = list((await db.execute(source_stmt)).scalars().all())
    assets = list((await db.execute(asset_stmt)).scalars().all())
    corpus_counts = dict(
        (
            await db.execute(
                select(SQLAsset.corpus_role, func.count(SQLAsset.id))
                .where(*asset_conditions)
                .group_by(SQLAsset.corpus_role)
            )
        ).all()
    )
    quality_counts = dict(
        (
            await db.execute(
                select(SQLAsset.quality_status, func.count(SQLAsset.id))
                .where(*asset_conditions)
                .group_by(SQLAsset.quality_status)
            )
        ).all()
    )
    return {
        "sources": [serialize_source(item) for item in sources],
        "assets": [serialize_asset(item) for item in assets],
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(assets) < total,
        },
        "facets": {"corpus_roles": corpus_counts, "quality_statuses": quality_counts},
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
    await _validate_project(
        db,
        project_id=asset.project_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=database_id,
    )
    if payload.expected_updated_at is not None and asset.updated_at != payload.expected_updated_at:
        raise AppException(
            ErrorCodes.RESOURCE_EXISTS.code,
            message="SQL 资产已被其他用户更新，请刷新后重试",
        )
    if payload.status is not None:
        validate_asset_status_transition(asset.status, payload.status)
    newly_published = payload.status == "published" and asset.status != "published"
    if payload.status == "published":
        target_corpus_role = payload.corpus_role or asset.corpus_role
        if target_corpus_role == "quarantine":
            raise ValidationException("隔离区 SQL 不允许发布；请先调整语料分区并重新审核")
        critical_risks = {"hardcoded_date", "hardcoded_id", "test_condition"}.intersection(
            asset.risk_flags or []
        )
        if target_corpus_role == "retrieval" and critical_risks:
            raise ValidationException(
                "检索库 SQL 含硬编码日期、ID 或测试条件，请参数化后重新上传，或移入评测集/隔离区"
            )
        if not asset.executable or (asset.validation_report or {}).get("status") != "pass":
            raise ValidationException("只有通过安全校验的只读 SQL 才能发布")
        inspection = await load_schema_inspection(db, database_id)
        fingerprint_matches, current_fingerprint = await evaluate_data_source_schema_fingerprint(
            db,
            data_source_id=database_id,
            schema_payload=inspection.schema_payload,
            stored_fingerprint=asset.schema_fingerprint,
        )
        if not fingerprint_matches:
            raise ValidationException("数据源 Schema 已变化，请重新上传并审核该 SQL")
        asset.schema_fingerprint = current_fingerprint
        if asset.status != "published":
            asset.approved_by = current_user.id
            asset.approved_at = datetime.now(UTC)
        asset.quality_status = "verified"
        asset.last_verified_at = datetime.now(UTC)
        asset.verification_metadata = {
            **(asset.verification_metadata or {}),
            "verified_by": current_user.id,
            "reason": payload.reason or "",
            "schema_fingerprint": current_fingerprint,
        }
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise ValidationException("SQL 资产标题不能为空")
        asset.title = title
    if payload.description is not None:
        asset.description = payload.description.strip()
    if payload.tags is not None:
        asset.tags = sorted({item.strip() for item in payload.tags if item.strip()})[:30]
    if payload.corpus_role is not None:
        if (
            payload.corpus_role == "quarantine"
            and asset.status == "published"
            and payload.status != "deprecated"
        ):
            raise ValidationException("已发布 SQL 进入隔离区前必须先废弃")
        asset.corpus_role = payload.corpus_role
    if payload.domain is not None:
        asset.domain = payload.domain.strip() or None
    if payload.owner is not None:
        asset.owner = payload.owner.strip() or None
    if payload.status is not None:
        asset.status = payload.status
        if payload.status == "deprecated":
            asset.quality_status = "deprecated"
        elif payload.status == "rejected":
            asset.quality_status = "failed"
        elif payload.status == "draft":
            asset.quality_status = "unverified"
    knowledge_promotion = None
    if newly_published and asset.corpus_role == "retrieval":
        knowledge_promotion = await promote_sql_asset_knowledge(
            db, asset=asset, user_id=current_user.id
        )
        # 将学习结果与审核事实一起落在资产上，后续可解释地回答“这条
        # 指标/字段知识来自哪里”，也避免只依赖一次请求的返回值。
        asset.verification_metadata = {
            **(asset.verification_metadata or {}),
            "knowledge_promotion": knowledge_promotion,
            "knowledge_promoted_at": datetime.now(UTC).isoformat(),
            "knowledge_promoted_by": current_user.id,
        }
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="sql_asset.update",
        resource_type="sql_asset",
        resource_id=asset.id,
        payload={
            "data_source_id": database_id,
            "status": payload.status,
            "reason": payload.reason,
            "updated_fields": sorted(payload.model_fields_set - {"expected_updated_at"}),
        },
    )
    result = serialize_asset(asset)
    if knowledge_promotion is not None:
        result["knowledge_promotion"] = knowledge_promotion
    return result


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
    source = await db.scalar(
        select(SQLAssetSource).where(
            SQLAssetSource.id == source_id,
            SQLAssetSource.tenant_id == tenant_id,
            SQLAssetSource.workspace_id == workspace_id,
            SQLAssetSource.data_source_id == database_id,
        )
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="SQL 资产源文件不存在")
    await _validate_project(
        db,
        project_id=source.project_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=database_id,
    )
    await db.delete(source)
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="sql_asset.source_delete",
        resource_type="sql_asset_source",
        resource_id=source_id,
        payload={"data_source_id": database_id},
    )


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
        retry_failed=payload.retry_failed,
    )
