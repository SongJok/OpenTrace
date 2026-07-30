from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
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
    ChatSession,
    EnterpriseSkill,
    SkillCatalogEntry,
    User,
    UserSkillInstallation,
)
from knowledge.access import classification_allows, resolve_access_context
from skills.catalog import _catalog_item, install_catalog_skill, sync_skillhub_catalog
from skills.distillation import DistillationSource, distill_enterprise_skill
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


class SkillSessionBindingRequest(BaseModel):
    session_id: str
    enabled_skills: list[str] = Field(default_factory=list)
    disabled_skills: list[str] = Field(default_factory=list)


class SkillSessionQuery(BaseModel):
    session_id: str


class SkillCatalogInstallRequest(BaseModel):
    catalog_skill_id: str = Field(min_length=1, max_length=36)


class SkillCatalogAvailabilityRequest(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=500)


_DISTILLABLE_SUFFIXES = {
    ".csv",
    ".docx",
    ".json",
    ".md",
    ".pdf",
    ".text",
    ".txt",
    ".yaml",
    ".yml",
}


def _enterprise_skill_item(row: EnterpriseSkill) -> dict[str, Any]:
    return {
        "id": row.id,
        "runtime_id": row.runtime_id,
        "name": row.name,
        "description": row.description,
        "value_summary": row.value_summary,
        "instructions": row.instructions,
        "source_files": list(row.source_files or []),
        "use_cases": list(row.use_cases or []),
        "classification": row.classification,
        "status": row.status,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "publication": "company",
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
                    limit
                )
            )
        )
        .scalars()
        .all()
    )
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
    return {
        "items": [_catalog_item(row) for row in rows],
        "policy": {
            "sync_enabled": bool(settings.skillhub_sync_enabled),
            "sync_interval_seconds": int(settings.skillhub_sync_interval_seconds),
            "sync_retry_seconds": int(settings.skillhub_sync_retry_seconds),
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
    except httpx.HTTPError as exc:
        raise AppException(
            ErrorCodes.INTERNAL_ERROR.code, message=f"SkillHub source unavailable: {exc}"
        )
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
        ]
    }


@router.post("/skills/company/distill", status_code=201)
async def distill_company_skill(
    request: Request,
    name: str = Form(..., min_length=1, max_length=128),
    description: str = Form(default="", max_length=4000),
    classification: str = Form(default="internal", pattern="^(public|internal|confidential)$"),
    paths: list[str] | None = Form(default=None),
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """从文件或文件夹生成公司发布的指令型 Skill；不执行任何上传代码。"""
    if not files or len(files) > 30:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="请选择 1 至 30 个文件")
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    max_file_bytes = max(1, int(settings.attachment_max_size_mb)) * 1024 * 1024
    max_total_bytes = min(max_file_bytes * 3, 60 * 1024 * 1024)
    total_bytes = 0
    sources: list[DistillationSource] = []
    source_files: list[dict[str, Any]] = []
    from gateway.api_gateway.routers.documents import _extract_text

    for index, upload in enumerate(files):
        filename = str(upload.filename or f"file-{index + 1}")
        relative_path = str(paths[index] if paths and index < len(paths) else filename)
        relative_path = re.sub(r"(^|/)\.\.?(/|$)", "/", relative_path).strip("/")[:512]
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in _DISTILLABLE_SUFFIXES:
            raise AppException(
                ErrorCodes.PARAM_INVALID.code,
                message=f"暂不支持蒸馏文件“{filename}”",
            )
        raw = await upload.read(max_file_bytes + 1)
        if not raw:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"文件“{filename}”为空")
        if len(raw) > max_file_bytes:
            raise AppException(
                ErrorCodes.PARAM_INVALID.code,
                message=f"文件“{filename}”不能超过 {settings.attachment_max_size_mb}MB",
            )
        total_bytes += len(raw)
        if total_bytes > max_total_bytes:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="蒸馏文件总大小不能超过 60MB")
        content = (await _extract_text(raw, filename)).strip()
        if not content:
            raise AppException(
                ErrorCodes.PARAM_INVALID.code,
                message=f"未能从“{filename}”提取可读文字",
            )
        digest = hashlib.sha256(raw).hexdigest()
        sources.append(
            DistillationSource(
                path=relative_path or filename,
                content=content,
                sha256=digest,
                size=len(raw),
            )
        )
        source_files.append(
            {
                "path": relative_path or filename,
                "sha256": digest,
                "size": len(raw),
                "content_type": upload.content_type or "application/octet-stream",
            }
        )

    try:
        distilled = distill_enterprise_skill(
            name=name.strip(), description=description.strip(), sources=sources
        )
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    existing = await db.scalar(
        select(EnterpriseSkill).where(
            EnterpriseSkill.tenant_id == tenant_id,
            EnterpriseSkill.workspace_id == workspace_id,
            EnterpriseSkill.source_digest == distilled.source_digest,
        )
    )
    if existing is not None:
        return {"skill": _enterprise_skill_item(existing), "deduplicated": True}

    skill_id = str(uuid.uuid4())
    row = EnterpriseSkill(
        id=skill_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        runtime_id=f"company-{skill_id}@1.0.0",
        name=name.strip(),
        description=description.strip(),
        value_summary=distilled.value_summary,
        instructions=distilled.instructions,
        source_digest=distilled.source_digest,
        source_files=source_files,
        use_cases=distilled.use_cases,
        classification=classification,
        status="published",
        created_by=current_user.id,
        published_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await write_audit_log(
        user_id=current_user.id,
        action="enterprise_skill.distill_publish",
        resource_type="enterprise_skill",
        resource_id=row.id,
        payload={
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "classification": classification,
            "source_count": len(source_files),
            "source_digest": distilled.source_digest,
        },
    )
    return {"skill": _enterprise_skill_item(row), "deduplicated": False}


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
    try:
        installed = marketplace.install_from_git(req.git_url, req.ref)
    except Exception as exc:  # noqa: BLE001
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"install failed: {exc}")
    return {"installed": installed.__dict__, "user_id": current_user.id}


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


@router.post("/skills/session/bind")
async def bind_session_skills(
    req: SkillSessionBindingRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == req.session_id,
            ChatSession.user_id == current_user.id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.workspace_id == workspace_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Session not found")
    enabled_skills = sorted(set(req.enabled_skills))
    disabled_skills = sorted(set(req.disabled_skills))
    account_ids = [item for item in enabled_skills if item.startswith("acct-")]
    if account_ids:
        allowed = set(
            (
                await db.execute(
                    select(UserSkillInstallation.installed_skill_id)
                    .join(
                        SkillCatalogEntry,
                        UserSkillInstallation.catalog_skill_id == SkillCatalogEntry.id,
                    )
                    .where(
                        UserSkillInstallation.user_id == current_user.id,
                        UserSkillInstallation.tenant_id == tenant_id,
                        UserSkillInstallation.workspace_id == workspace_id,
                        UserSkillInstallation.status == "installed",
                        SkillCatalogEntry.status == "active",
                        UserSkillInstallation.installed_skill_id.in_(account_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        invalid = sorted(set(account_ids) - allowed)
        if invalid:
            raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="账户无权启用该 Skill")
    company_ids = [item for item in enabled_skills if item.startswith("company-")]
    if company_ids:
        access = await resolve_access_context(
            db,
            user=current_user,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        company_skills = list(
            (
                await db.execute(
                    select(EnterpriseSkill).where(
                        EnterpriseSkill.tenant_id == tenant_id,
                        EnterpriseSkill.workspace_id == workspace_id,
                        EnterpriseSkill.status == "published",
                        EnterpriseSkill.runtime_id.in_(company_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        allowed_company_ids = {
            skill.runtime_id
            for skill in company_skills
            if classification_allows(access.clearance, skill.classification)
        }
        if sorted(set(company_ids) - allowed_company_ids):
            raise AppException(
                ErrorCodes.PERMISSION_DENIED.code, message="当前企业无权启用该 Skill"
            )
    session.enabled_skills = enabled_skills
    session.disabled_skills = disabled_skills
    await db.commit()
    return {
        "session_id": req.session_id,
        "enabled_skills": enabled_skills,
        "disabled_skills": disabled_skills,
    }


@router.get("/skills/session/{session_id}")
async def get_session_skills(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(
        build_tenant_metadata(request, user_id=current_user.id)
    )
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.workspace_id == workspace_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Session not found")
    return {
        "session_id": session_id,
        "enabled_skills": list(session.enabled_skills or []),
        "disabled_skills": list(session.disabled_skills or []),
    }
