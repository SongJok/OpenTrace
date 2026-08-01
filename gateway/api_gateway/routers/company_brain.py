"""唯一公司绑定与企业大脑管理 API。"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.admin import get_current_admin_user
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.routers.documents import _extract_text, _read_document_upload
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.security.resource_scope import normalized_tenant_scope
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import CompanyBrainSource, CompanyBrainVersion, CompanyProfile, User
from services.company_brain import (
    COMPANY_BRAIN_FOLDERS,
    company_brain_source_payload,
    company_brain_version_payload,
    company_profile_payload,
    create_company_brain_draft,
    get_company_profile,
    initialize_company_brain,
    normalize_memory_tier,
    publish_company_brain_version,
    validate_folder,
)

router = APIRouter()


class CompanyBindingInput(BaseModel):
    legal_name: str = Field(min_length=2, max_length=255)
    short_name: str = Field(min_length=1, max_length=32)
    description: str = Field(default="", max_length=4000)


class CompanyBrainManualSourceInput(BaseModel):
    folder: Literal["文化", "行政", "前端", "后端", "产品", "客服", "财务", "数据"]
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=180_000)
    memory_tier: Literal["auto", "long", "medium", "short"] = "auto"
    salience: float = Field(default=0.6, ge=0.0, le=1.0)


class CompanyBrainDraftInput(BaseModel):
    content: str = Field(min_length=1, max_length=220_000)
    change_summary: str = Field(default="管理员在线编辑 COMPANY.md", max_length=4000)


class CompanyBrainPublishInput(BaseModel):
    version_id: str | None = Field(default=None, max_length=36)


def _company_error(reason: str) -> AppException:
    messages = {
        "company_already_bound": "当前项目已经绑定公司，不能改绑为另一家公司",
        "company_not_bound": "请先绑定当前项目唯一公司",
        "unsupported_company_brain_folder": "企业大脑目录只能是文化、行政、前端、后端、产品、客服、财务或数据",
        "unsupported_company_brain_tier": "不支持的企业大脑记忆层级",
        "company_brain_tier_folder_mismatch": "长期/中期层级必须由目录规则决定；管理员明确记录可选择短期",
        "company_md_missing_memory_sections": "COMPANY.md 必须完整保留长期、中期和短期记忆三个章节",
        "company_md_identity_header_required": "COMPANY.md 必须以凸显企业大脑的标题开头",
        "company_md_hard_limit_exceeded": "COMPANY.md 不能超过 20 万字",
        "protected_long_term_memory_exceeds_hard_limit": "受保护的长期记忆已超过容量，系统拒绝自动删除或压缩",
        "company_brain_draft_not_found": "未找到可发布的 COMPANY.md 草稿",
        "company_brain_draft_not_publishable": "该版本不属于当前公司或已经发布",
        "company_brain_source_contains_secret": "资料包含疑似密钥或认证信息，已拒绝进入企业大脑",
        "company_brain_source_not_reviewable": "只有待管理员审核的自主学习候选可以批准",
        "company_brain_source_not_reprocessable": "已停用的企业大脑来源不能重新处理",
    }
    return AppException(
        ErrorCodes.PARAM_INVALID.code,
        message=messages.get(reason, "企业大脑数据校验失败"),
        details={"reason": reason},
    )


def _request_scope(request: Request, user: User) -> tuple[str, str]:
    return normalized_tenant_scope(build_tenant_metadata(request, user_id=user.id))


async def _scoped_profile(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    for_update: bool = False,
) -> CompanyProfile | None:
    tenant_id, workspace_id = _request_scope(request, user)
    return await get_company_profile(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        for_update=for_update,
    )


@router.get("/company/profile")
async def current_company_profile(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """公司简称是界面品牌，不属于敏感内容，因此登录页和分享页也可读取。"""

    payload = company_profile_payload(await get_company_profile(db))
    return {
        **payload,
        "id": None,
        "legal_name": "",
        "description": "",
        "current_version_id": None,
        "last_maintenance_at": None,
    }


@router.put("/admin/company/profile")
async def bind_company(
    request: Request,
    payload: CompanyBindingInput,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    legal_name = payload.legal_name.strip()
    short_name = payload.short_name.strip()
    tenant_id, workspace_id = _request_scope(request, current_user)
    profile = await get_company_profile(db, for_update=True)
    if profile is not None:
        if (
            profile.tenant_id != tenant_id
            or profile.workspace_id != workspace_id
            or profile.legal_name != legal_name
        ):
            raise _company_error("company_already_bound")
        profile.short_name = short_name
        profile.description = payload.description.strip()
        await db.commit()
        return company_profile_payload(profile)

    profile = CompanyProfile(
        id=str(uuid.uuid4()),
        singleton_key="primary",
        legal_name=legal_name,
        short_name=short_name,
        description=payload.description.strip(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=current_user.id,
    )
    db.add(profile)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise _company_error("company_already_bound") from exc
    await initialize_company_brain(db, profile=profile, actor_id=current_user.id)
    await db.commit()
    return company_profile_payload(profile)


@router.get("/company/brain")
async def current_company_brain(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(db, request=request, user=current_user)
    if profile is None:
        return {
            "profile": company_profile_payload(None),
            "folders": [
                {"name": folder, "source_count": 0, "ready_count": 0, "review_count": 0}
                for folder in COMPANY_BRAIN_FOLDERS
            ],
            "published": None,
            "draft": None,
        }
    counts = (
        await db.execute(
            select(
                CompanyBrainSource.folder,
                func.count(CompanyBrainSource.id),
                func.count(CompanyBrainSource.id).filter(CompanyBrainSource.status == "ready"),
                func.count(CompanyBrainSource.id).filter(CompanyBrainSource.status == "review"),
            )
            .where(
                CompanyBrainSource.company_id == profile.id,
                CompanyBrainSource.active.is_(True),
            )
            .group_by(CompanyBrainSource.folder)
        )
    ).all()
    by_folder = {
        str(folder): (int(total), int(ready), int(review))
        for folder, total, ready, review in counts
    }
    published = (
        await db.scalar(
            select(CompanyBrainVersion).where(
                CompanyBrainVersion.id == profile.current_version_id,
                CompanyBrainVersion.company_id == profile.id,
            )
        )
        if profile.current_version_id
        else None
    )
    is_admin = current_user.role == "admin" or bool(current_user.is_superuser)
    draft = (
        await db.scalar(
            select(CompanyBrainVersion)
            .where(
                CompanyBrainVersion.company_id == profile.id,
                CompanyBrainVersion.status == "draft",
            )
            .order_by(CompanyBrainVersion.version.desc())
        )
        if is_admin
        else None
    )
    return {
        "profile": company_profile_payload(profile),
        "folders": [
            {
                "name": folder,
                "default_tier": "long" if folder in {"文化", "行政"} else "medium",
                "source_count": by_folder.get(folder, (0, 0, 0))[0],
                "ready_count": by_folder.get(folder, (0, 0, 0))[1],
                "review_count": by_folder.get(folder, (0, 0, 0))[2],
            }
            for folder in COMPANY_BRAIN_FOLDERS
        ],
        "published": company_brain_version_payload(published, include_content=is_admin),
        "draft": company_brain_version_payload(draft, include_content=is_admin),
    }


@router.get("/admin/company/brain/sources")
async def list_company_brain_sources(
    request: Request,
    folder: str | None = Query(default=None, max_length=20),
    include_inactive: bool = False,
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(db, request=request, user=current_user)
    if profile is None:
        raise _company_error("company_not_bound")
    statement = select(CompanyBrainSource).where(CompanyBrainSource.company_id == profile.id)
    if folder:
        try:
            normalized_folder = validate_folder(folder)
        except ValueError as exc:
            raise _company_error(str(exc)) from exc
        statement = statement.where(CompanyBrainSource.folder == normalized_folder)
    if not include_inactive:
        statement = statement.where(CompanyBrainSource.active.is_(True))
    rows = list(
        (await db.execute(statement.order_by(CompanyBrainSource.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return {"items": [company_brain_source_payload(row) for row in rows]}


async def _create_source(
    db: AsyncSession,
    *,
    profile: CompanyProfile,
    folder: str,
    memory_tier: str,
    source_type: str,
    title: str,
    content: str,
    salience: float,
    current_user: User,
    metadata: dict[str, Any],
) -> CompanyBrainSource:
    source = CompanyBrainSource(
        id=str(uuid.uuid4()),
        company_id=profile.id,
        folder=folder,
        memory_tier=memory_tier,
        source_type=source_type,
        title=title,
        source_content=content,
        processed_content="",
        source_metadata={**metadata, "isolation": "internal_company_brain_only"},
        status="pending",
        active=True,
        salience=salience,
        created_by=current_user.id,
    )
    db.add(source)
    await db.flush()
    return source


@router.post("/admin/company/brain/sources/manual", status_code=202)
async def create_manual_company_brain_source(
    request: Request,
    payload: CompanyBrainManualSourceInput,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(db, request=request, user=current_user)
    if profile is None:
        raise _company_error("company_not_bound")
    try:
        folder = validate_folder(payload.folder)
        tier = normalize_memory_tier(folder, payload.memory_tier)
    except ValueError as exc:
        raise _company_error(str(exc)) from exc
    source = await _create_source(
        db,
        profile=profile,
        folder=folder,
        memory_tier=tier,
        source_type="manual",
        title=payload.title.strip(),
        content=payload.content.strip(),
        salience=payload.salience,
        current_user=current_user,
        metadata={"entry_mode": "administrator_manual"},
    )
    await db.commit()
    return company_brain_source_payload(source, include_raw=True)


@router.post("/admin/company/brain/sources/upload", status_code=202)
async def upload_company_brain_source(
    request: Request,
    file: UploadFile = File(...),
    folder: str = Form(...),
    memory_tier: str = Form("auto"),
    title: str | None = Form(None),
    salience: float = Form(0.6),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(db, request=request, user=current_user)
    if profile is None:
        raise _company_error("company_not_bound")
    try:
        normalized_folder = validate_folder(folder)
        tier = normalize_memory_tier(normalized_folder, memory_tier)
    except ValueError as exc:
        raise _company_error(str(exc)) from exc
    raw = await _read_document_upload(file)
    filename = file.filename or "企业资料"
    content = (await _extract_text(raw, filename)).strip()
    if not content:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="文档未提取到可处理文字")
    source = await _create_source(
        db,
        profile=profile,
        folder=normalized_folder,
        memory_tier=tier,
        source_type="upload",
        title=(title or filename).strip()[:255],
        content=content[:180_000],
        salience=min(1.0, max(0.0, salience)),
        current_user=current_user,
        metadata={"filename": filename, "size": len(raw), "content_type": file.content_type},
    )
    await db.commit()
    return company_brain_source_payload(source)


@router.delete("/admin/company/brain/sources/{source_id}")
async def deactivate_company_brain_source(
    request: Request,
    source_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(db, request=request, user=current_user)
    if profile is None:
        raise _company_error("company_not_bound")
    source = await db.scalar(
        select(CompanyBrainSource).where(
            CompanyBrainSource.id == source_id,
            CompanyBrainSource.company_id == profile.id,
        )
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="企业大脑来源不存在")
    source.active = False
    source.status = "rebuild"
    await db.commit()
    return {"status": "deactivated", "id": source.id}


@router.post("/admin/company/brain/sources/{source_id}/approve", status_code=202)
async def approve_company_brain_source(
    request: Request,
    source_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(db, request=request, user=current_user)
    if profile is None:
        raise _company_error("company_not_bound")
    source = await db.scalar(
        select(CompanyBrainSource).where(
            CompanyBrainSource.id == source_id,
            CompanyBrainSource.company_id == profile.id,
            CompanyBrainSource.active.is_(True),
        )
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="企业大脑来源不存在")
    if source.status != "review" or source.source_type != "conversation":
        raise _company_error("company_brain_source_not_reviewable")
    metadata = dict(source.source_metadata or {})
    metadata["review_approved_by"] = current_user.id
    source.source_metadata = metadata
    # Worker 负责将候选提升为 ready 并重编译，API 只提交持久状态。
    source.status = "pending"
    source.error_message = None
    await db.commit()
    return company_brain_source_payload(source)


@router.post("/admin/company/brain/sources/{source_id}/retry", status_code=202)
async def retry_company_brain_source(
    request: Request,
    source_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(db, request=request, user=current_user)
    if profile is None:
        raise _company_error("company_not_bound")
    source = await db.scalar(
        select(CompanyBrainSource).where(
            CompanyBrainSource.id == source_id,
            CompanyBrainSource.company_id == profile.id,
        )
    )
    if source is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="企业大脑来源不存在")
    if not source.active:
        raise _company_error("company_brain_source_not_reprocessable")
    source.status = "pending"
    source.processed_content = ""
    source.processed_at = None
    source.processing_attempts = 0
    source.error_message = None
    metadata = dict(source.source_metadata or {})
    metadata["reprocess_requested_by"] = current_user.id
    source.source_metadata = metadata
    await db.commit()
    return company_brain_source_payload(source)


@router.put("/admin/company/brain/draft")
async def save_company_brain_draft(
    request: Request,
    payload: CompanyBrainDraftInput,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(
        db,
        request=request,
        user=current_user,
        for_update=True,
    )
    if profile is None:
        raise _company_error("company_not_bound")
    try:
        version = await create_company_brain_draft(
            db,
            profile=profile,
            content=payload.content,
            trigger="administrator_edit",
            created_by=current_user.id,
            change_summary=payload.change_summary,
        )
    except ValueError as exc:
        raise _company_error(str(exc)) from exc
    await db.commit()
    return company_brain_version_payload(version) or {}


@router.post("/admin/company/brain/publish")
async def publish_company_brain_draft(
    request: Request,
    payload: CompanyBrainPublishInput,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await _scoped_profile(
        db,
        request=request,
        user=current_user,
        for_update=True,
    )
    if profile is None:
        raise _company_error("company_not_bound")
    statement = select(CompanyBrainVersion).where(
        CompanyBrainVersion.company_id == profile.id,
        CompanyBrainVersion.status == "draft",
    )
    if payload.version_id:
        statement = statement.where(CompanyBrainVersion.id == payload.version_id)
    version = await db.scalar(statement.order_by(CompanyBrainVersion.version.desc()))
    if version is None:
        raise _company_error("company_brain_draft_not_found")
    try:
        await publish_company_brain_version(
            db, profile=profile, version=version, published_by=current_user.id
        )
    except ValueError as exc:
        raise _company_error(str(exc)) from exc
    await db.commit()
    return company_brain_version_payload(version) or {}
