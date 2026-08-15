from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import normalized_tenant_scope
from gateway.api_gateway.routers.admin import get_current_admin_user
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.audit.logger import write_audit_log
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import (
    EnterpriseSkill,
    SkillCatalogEntry,
    User,
    UserSkillInstallation,
)
from knowledge.access import classification_allows, resolve_access_context
from skills.catalog import _catalog_item, install_catalog_skill, sync_skillhub_catalog
from skills.company import (
    MAX_FILE_BYTES,
    MAX_PACKAGE_FILES,
    CompanySkillUploadFile,
    public_source_files,
    validate_company_skill_package,
)
from skills.local_store import local_skill_store
from skills.store.marketplace import marketplace

router = APIRouter()


class SkillInstallRequest(BaseModel):
    git_url: str
    ref: str = Field(default="main")


class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    version: str = Field(default="0.1.0")
    entrypoint: str = Field(default="main.py")
    code: str = Field(default="")
    description: str = Field(default="")
    skill_type: str = Field(default="generic")
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    data_source_id: str = Field(default="")


class SkillTestRequest(BaseModel):
    test_input: dict[str, Any] = Field(default_factory=dict)


class SkillUninstallRequest(BaseModel):
    skill_id: str


class SkillCatalogInstallRequest(BaseModel):
    catalog_skill_id: str = Field(min_length=1, max_length=36)


class SkillCatalogAvailabilityRequest(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=500)


def _ensure_enterprise_skill_local(row: EnterpriseSkill) -> bool:
    tenant_id = str(getattr(row, "tenant_id", ""))
    workspace_id = str(getattr(row, "workspace_id", ""))
    source_digest = str(getattr(row, "source_digest", ""))
    if not tenant_id or not workspace_id or not source_digest:
        return True
    try:
        if not local_skill_store.company_available(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            runtime_id=row.runtime_id,
            source_digest=source_digest,
        ):
            stored_files = [
                item
                for item in list(row.source_files or [])
                if isinstance(item, dict) and isinstance(item.get("content"), str)
            ]
            if stored_files:
                local_skill_store.write_company_skill_package(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    runtime_id=row.runtime_id,
                    name=row.name,
                    description=row.value_summary or row.description,
                    classification=row.classification,
                    source_digest=source_digest,
                    files=stored_files,
                )
            else:
                # 兼容历史上由平台蒸馏的单文件记录；新入口只接收用户已蒸馏的 Skill 包。
                local_skill_store.write_company_skill(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    runtime_id=row.runtime_id,
                    name=row.name,
                    description=row.value_summary or row.description,
                    instructions=row.instructions,
                    classification=row.classification,
                    source_digest=source_digest,
                )
    except (AttributeError, OSError, ValueError):
        return False
    return True


def _enterprise_skill_item(row: EnterpriseSkill) -> dict[str, Any]:
    version = row.runtime_id.rsplit("@", 1)[-1] if "@" in row.runtime_id else "1.0.0"
    uploaded = any(
        isinstance(item, dict) and isinstance(item.get("content"), str)
        for item in list(row.source_files or [])
    )
    return {
        "id": row.id,
        "runtime_id": row.runtime_id,
        "name": row.name,
        "description": row.value_summary or row.description,
        "value_summary": row.value_summary,
        "version": version,
        "source_files": public_source_files(row.source_files),
        "use_cases": list(row.use_cases or []),
        "classification": row.classification,
        "status": row.status,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "publication": "company",
        "origin": "uploaded" if uploaded else "legacy_distilled",
        "execution_policy": "context_only",
        "active_distillation": False,
        "local_available": _ensure_enterprise_skill_local(row),
    }


@router.get("/skills/catalog")
async def list_skill_catalog(
    request: Request,
    sort: str = Query(default="popular", pattern="^(popular|recent)$"),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    stmt = select(SkillCatalogEntry).where(SkillCatalogEntry.status == "active")
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(SkillCatalogEntry.name.ilike(term), SkillCatalogEntry.description.ilike(term))
        )
    order = SkillCatalogEntry.rank_popular if sort == "popular" else SkillCatalogEntry.rank_recent
    rows = list(
        (
            await db.execute(
                stmt.order_by(order.asc().nullslast(), SkillCatalogEntry.ai_score.desc()).limit(
                    max(limit * 5, 100)
                )
            )
        )
        .scalars()
        .all()
    )
    rows = [
        row for row in rows if local_skill_store.catalog_available(dict(row.source_metadata or {}))
    ][:limit]
    installs = list(
        (
            await db.execute(
                select(UserSkillInstallation).where(
                    UserSkillInstallation.user_id == current_user.id,
                    UserSkillInstallation.tenant_id == tenant_id,
                    UserSkillInstallation.workspace_id == workspace_id,
                    UserSkillInstallation.catalog_skill_id.in_([row.id for row in rows] or ["-"]),
                )
            )
        )
        .scalars()
        .all()
    )
    by_catalog = {item.catalog_skill_id: item for item in installs}
    return {"items": [_catalog_item(row, by_catalog.get(row.id)) for row in rows], "sort": sort}


@router.get("/skills/catalog/admin")
async def list_admin_skill_catalog(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(SkillCatalogEntry)
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(SkillCatalogEntry.name.ilike(term), SkillCatalogEntry.description.ilike(term))
        )
    rows = list(
        (
            await db.execute(
                stmt.order_by(
                    SkillCatalogEntry.status.asc(), SkillCatalogEntry.rank_popular.asc().nullslast()
                ).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    rows = [
        row for row in rows if local_skill_store.catalog_available(dict(row.source_metadata or {}))
    ]
    return {
        "items": [_catalog_item(row) for row in rows],
        "policy": {
            "sync_enabled": bool(settings.skillhub_sync_enabled),
            "sync_interval_seconds": int(settings.skillhub_sync_interval_seconds),
            "sync_retry_seconds": int(settings.skillhub_sync_retry_seconds),
            "sync_hour": int(settings.skillhub_sync_hour),
            "sync_minute": int(settings.skillhub_sync_minute),
            "sync_timezone": str(settings.skillhub_sync_timezone),
            "delivery": "local_mirror",
            "catalog_size": int(settings.skillhub_catalog_size),
            "retention": "append_only",
        },
        "user_id": current_user.id,
    }


@router.post("/skills/catalog/sync")
async def sync_catalog(
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    return {"synced": await sync_skillhub_catalog(), "user_id": current_user.id}


@router.patch("/skills/catalog/{catalog_id}/availability")
async def set_catalog_availability(
    catalog_id: str,
    payload: SkillCatalogAvailabilityRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(SkillCatalogEntry, catalog_id)
    if row is None:
        raise AppException(
            ErrorCodes.RESOURCE_NOT_FOUND.code, message="Skill catalog entry not found"
        )
    row.status = "active" if payload.enabled else "disabled"
    metadata = dict(row.source_metadata or {})
    metadata["platform_note"] = payload.reason.strip()
    metadata["platform_disabled_by"] = None if payload.enabled else current_user.id
    metadata["platform_disabled_at"] = None if payload.enabled else datetime.now(UTC).isoformat()
    row.source_metadata = metadata
    await db.commit()
    await db.refresh(row)
    return {"item": _catalog_item(row), "user_id": current_user.id}


@router.post("/skills/catalog/install")
async def install_catalog_entry(
    request: Request,
    req: SkillCatalogInstallRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    try:
        item = await install_catalog_skill(
            catalog_id=req.catalog_skill_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
    except PermissionError as exc:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message=str(exc))
    except (ValueError, OSError) as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc))
    return {"installed": item}


@router.get("/skills/installed/me")
async def list_my_installed_skills(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    rows = list(
        (
            await db.execute(
                select(UserSkillInstallation, SkillCatalogEntry)
                .join(
                    SkillCatalogEntry,
                    UserSkillInstallation.catalog_skill_id == SkillCatalogEntry.id,
                )
                .where(
                    UserSkillInstallation.user_id == current_user.id,
                    UserSkillInstallation.tenant_id == tenant_id,
                    UserSkillInstallation.workspace_id == workspace_id,
                    UserSkillInstallation.status == "installed",
                )
                .order_by(UserSkillInstallation.installed_at.desc())
            )
        ).all()
    )
    return {"items": [_catalog_item(catalog, installation) for installation, catalog in rows]}


@router.get("/skills/company")
async def list_company_skills(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    rows = list(
        (
            await db.execute(
                select(EnterpriseSkill)
                .where(
                    EnterpriseSkill.tenant_id == tenant_id,
                    EnterpriseSkill.workspace_id == workspace_id,
                    EnterpriseSkill.status == "published",
                )
                .order_by(EnterpriseSkill.published_at.desc(), EnterpriseSkill.name)
            )
        )
        .scalars()
        .all()
    )
    access = await resolve_access_context(
        db,
        user=current_user,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    return {
        "items": [
            _enterprise_skill_item(row)
            for row in rows
            if classification_allows(access.clearance, row.classification)
            and _ensure_enterprise_skill_local(row)
        ]
    }


@router.post("/skills/company/upload", status_code=201)
async def upload_company_skill(
    request: Request,
    classification: str = Form(default="internal", pattern="^(public|internal|confidential)$"),
    paths: list[str] | None = Form(default=None),
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """发布用户已蒸馏的公司 Skill 包；平台只校验和存储，不执行主动蒸馏。"""
    if not files or len(files) > MAX_PACKAGE_FILES:
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message=f"请选择 1 至 {MAX_PACKAGE_FILES} 个 Skill 包文件",
        )
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    uploads: list[CompanySkillUploadFile] = []
    for index, upload in enumerate(files):
        filename = str(upload.filename or f"file-{index + 1}")
        relative_path = str(paths[index] if paths and index < len(paths) else filename)
        raw = await upload.read(MAX_FILE_BYTES + 1)
        uploads.append(
            CompanySkillUploadFile(
                path=relative_path or filename,
                content=raw,
                content_type=upload.content_type or "text/plain",
            )
        )
    try:
        package = validate_company_skill_package(uploads)
    except ValueError as exc:
        messages = {
            "company_skill_requires_exactly_one_skill_md": "Skill 包必须且只能包含一个 SKILL.md",
            "company_skill_package_too_large": "Skill 包总大小不能超过 12MB",
            "company_skill_md_content_invalid": "SKILL.md 内容过短、为空或超过限制",
            "company_skill_secret_detected": "Skill 包疑似包含密钥或私钥，请移除敏感信息后重试",
        }
        code = str(exc).split(":", 1)[0]
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message=messages.get(code, f"Skill 包校验失败：{exc}"),
        ) from exc
    existing = await db.scalar(
        select(EnterpriseSkill).where(
            EnterpriseSkill.tenant_id == tenant_id,
            EnterpriseSkill.workspace_id == workspace_id,
            EnterpriseSkill.source_digest == package.source_digest,
        )
    )
    if existing is not None:
        republished = existing.status != "published"
        classification_changed = existing.classification != classification
        if republished:
            existing.status = "published"
            existing.published_by = current_user.id
            existing.published_at = datetime.now(UTC)
        if classification_changed:
            existing.classification = classification
        if republished or classification_changed:
            await db.commit()
            await db.refresh(existing)
        if not _ensure_enterprise_skill_local(existing):
            raise AppException(
                ErrorCodes.INTERNAL_ERROR.code, message="公司 Skill 写入本地镜像失败"
            )
        if republished or classification_changed:
            await write_audit_log(
                user_id=current_user.id,
                action=(
                    "enterprise_skill.republish"
                    if republished
                    else "enterprise_skill.classification_update"
                ),
                resource_type="enterprise_skill",
                resource_id=existing.id,
                payload={
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "classification": existing.classification,
                    "package_digest": existing.source_digest,
                },
            )
        return {
            "skill": _enterprise_skill_item(existing),
            "deduplicated": not (republished or classification_changed),
            "republished": republished,
        }

    skill_id = str(uuid.uuid4())
    row = EnterpriseSkill(
        id=skill_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        runtime_id=f"company-{skill_id}@{package.version}",
        name=package.name,
        description=package.description,
        value_summary=package.description,
        instructions=package.instructions,
        source_digest=package.source_digest,
        source_files=package.files,
        use_cases=package.use_cases,
        classification=classification,
        status="published",
        created_by=current_user.id,
        published_by=current_user.id,
    )
    if not _ensure_enterprise_skill_local(row):
        raise AppException(ErrorCodes.INTERNAL_ERROR.code, message="公司 Skill 写入本地镜像失败")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await write_audit_log(
        user_id=current_user.id,
        action="enterprise_skill.upload_publish",
        resource_type="enterprise_skill",
        resource_id=row.id,
        payload={
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "classification": classification,
            "package_file_count": len(package.files),
            "package_digest": package.source_digest,
            "version": package.version,
            "active_distillation": False,
        },
    )
    return {"skill": _enterprise_skill_item(row), "deduplicated": False, "republished": False}


@router.delete("/skills/company/{skill_id}")
async def archive_company_skill(
    skill_id: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """从问答上下文中移除公司 Skill；保留记录和审计以支持重新发布。"""
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    row = await db.scalar(
        select(EnterpriseSkill).where(
            EnterpriseSkill.id == skill_id,
            EnterpriseSkill.tenant_id == tenant_id,
            EnterpriseSkill.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="公司 Skill 不存在")
    row.status = "archived"
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="enterprise_skill.archive",
        resource_type="enterprise_skill",
        resource_id=row.id,
        payload={"tenant_id": tenant_id, "workspace_id": workspace_id},
    )
    return {"removed": True, "skill_id": row.id}


@router.delete("/skills/installations/{installation_id}")
async def uninstall_my_skill(
    installation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    row = await db.scalar(
        select(UserSkillInstallation).where(
            UserSkillInstallation.id == installation_id,
            UserSkillInstallation.user_id == current_user.id,
            UserSkillInstallation.tenant_id == tenant_id,
            UserSkillInstallation.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(
            ErrorCodes.RESOURCE_NOT_FOUND.code, message="Skill installation not found"
        )
    marketplace.uninstall(row.installed_skill_id)
    row.status = "uninstalled"
    await db.commit()
    return {"removed": True, "installation_id": installation_id}


@router.get("/skills")
async def list_skills(current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    items = marketplace.list_installed()
    return {"items": [item.__dict__ for item in items], "user_id": current_user.id}


@router.post("/skills/install")
async def install_skill(
    req: SkillInstallRequest, current_user: User = Depends(get_current_admin_user)
) -> dict[str, Any]:
    del req, current_user
    raise AppException(
        ErrorCodes.PERMISSION_DENIED.code,
        message="外部 Git 即时安装已停用；请等待每天 06:30 的本地镜像同步或由管理员手动同步目录",
    )


@router.post("/skills/create")
async def create_skill(
    req: SkillCreateRequest, current_user: User = Depends(get_current_admin_user)
) -> dict[str, Any]:
    try:
        skill = marketplace.create_local(
            name=req.name,
            version=req.version,
            entrypoint=req.entrypoint,
            code=req.code,
            description=req.description,
            skill_type=req.skill_type,
            test_cases=req.test_cases,
            data_source_id=req.data_source_id,
        )
    except PermissionError as exc:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message=str(exc))
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc))
    return {"skill": skill.__dict__, "user_id": current_user.id}


@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: str, current_user: User = Depends(get_current_admin_user)
) -> dict[str, Any]:
    skill = marketplace.get_skill(skill_id)
    if skill is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")
    return {"skill": skill.__dict__, "user_id": current_user.id}


@router.post("/skills/{skill_id}/test")
async def test_skill(
    skill_id: str, req: SkillTestRequest, current_user: User = Depends(get_current_admin_user)
) -> dict[str, Any]:
    result = marketplace.test_skill(skill_id, req.test_input)
    return {"result": result, "user_id": current_user.id}


@router.post("/skills/uninstall")
async def uninstall_skill(
    req: SkillUninstallRequest, current_user: User = Depends(get_current_admin_user)
) -> dict[str, Any]:
    ok = marketplace.uninstall(req.skill_id)
    if not ok:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")
    return {"removed": True, "skill_id": req.skill_id, "user_id": current_user.id}
