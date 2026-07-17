from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.admin import get_current_admin_user
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.resource_scope import normalized_tenant_scope
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import ChatSession, SkillCatalogEntry, User, UserSkillInstallation
from skills.catalog import _catalog_item, install_catalog_skill, sync_skillhub_catalog
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


@router.get("/skills/catalog")
async def list_skill_catalog(
    request: Request,
    sort: str = Query(default="popular", pattern="^(popular|recent)$"),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(request, user_id=current_user.id))
    stmt = select(SkillCatalogEntry).where(SkillCatalogEntry.status == "active")
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(SkillCatalogEntry.name.ilike(term), SkillCatalogEntry.description.ilike(term)))
    order = SkillCatalogEntry.rank_popular if sort == "popular" else SkillCatalogEntry.rank_recent
    rows = list((await db.execute(stmt.order_by(order.asc().nullslast(), SkillCatalogEntry.ai_score.desc()).limit(limit))).scalars().all())
    installs = list((await db.execute(select(UserSkillInstallation).where(
        UserSkillInstallation.user_id == current_user.id,
        UserSkillInstallation.tenant_id == tenant_id,
        UserSkillInstallation.workspace_id == workspace_id,
        UserSkillInstallation.catalog_skill_id.in_([row.id for row in rows] or ["-"]),
    ))).scalars().all())
    by_catalog = {item.catalog_skill_id: item for item in installs}
    return {"items": [_catalog_item(row, by_catalog.get(row.id)) for row in rows], "sort": sort}


@router.post("/skills/catalog/sync")
async def sync_catalog(
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    return {"synced": await sync_skillhub_catalog(), "user_id": current_user.id}


@router.post("/skills/catalog/install")
async def install_catalog_entry(
    request: Request,
    req: SkillCatalogInstallRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(request, user_id=current_user.id))
    try:
        item = await install_catalog_skill(
            catalog_id=req.catalog_skill_id, user_id=current_user.id,
            tenant_id=tenant_id, workspace_id=workspace_id,
        )
    except PermissionError as exc:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message=str(exc))
    except (ValueError, OSError) as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc))
    except httpx.HTTPError as exc:
        raise AppException(ErrorCodes.INTERNAL_ERROR.code, message=f"SkillHub source unavailable: {exc}")
    return {"installed": item}


@router.get("/skills/installed/me")
async def list_my_installed_skills(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(request, user_id=current_user.id))
    rows = list((await db.execute(
        select(UserSkillInstallation, SkillCatalogEntry)
        .join(SkillCatalogEntry, UserSkillInstallation.catalog_skill_id == SkillCatalogEntry.id)
        .where(
            UserSkillInstallation.user_id == current_user.id,
            UserSkillInstallation.tenant_id == tenant_id,
            UserSkillInstallation.workspace_id == workspace_id,
            UserSkillInstallation.status == "installed",
        )
        .order_by(UserSkillInstallation.installed_at.desc())
    )).all())
    return {"items": [_catalog_item(catalog, installation) for installation, catalog in rows]}


@router.delete("/skills/installations/{installation_id}")
async def uninstall_my_skill(
    installation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id, workspace_id = normalized_tenant_scope(build_tenant_metadata(request, user_id=current_user.id))
    row = await db.scalar(select(UserSkillInstallation).where(
        UserSkillInstallation.id == installation_id,
        UserSkillInstallation.user_id == current_user.id,
        UserSkillInstallation.tenant_id == tenant_id,
        UserSkillInstallation.workspace_id == workspace_id,
    ))
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Skill installation not found")
    marketplace.uninstall(row.installed_skill_id)
    row.status = "uninstalled"
    await db.commit()
    return {"removed": True, "installation_id": installation_id}


@router.get("/skills")
async def list_skills(current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    items = marketplace.list_installed()
    return {"items": [item.__dict__ for item in items], "user_id": current_user.id}


@router.post("/skills/install")
async def install_skill(req: SkillInstallRequest, current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    try:
        installed = marketplace.install_from_git(req.git_url, req.ref)
    except Exception as exc:  # noqa: BLE001
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"install failed: {exc}")
    return {"installed": installed.__dict__, "user_id": current_user.id}


@router.post("/skills/create")
async def create_skill(req: SkillCreateRequest, current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
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
async def get_skill(skill_id: str, current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    skill = marketplace.get_skill(skill_id)
    if skill is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")
    return {"skill": skill.__dict__, "user_id": current_user.id}


@router.post("/skills/{skill_id}/test")
async def test_skill(skill_id: str, req: SkillTestRequest, current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    result = marketplace.test_skill(skill_id, req.test_input)
    return {"result": result, "user_id": current_user.id}


@router.post("/skills/uninstall")
async def uninstall_skill(req: SkillUninstallRequest, current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    ok = marketplace.uninstall(req.skill_id)
    if not ok:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")
    return {"removed": True, "skill_id": req.skill_id, "user_id": current_user.id}


@router.post("/skills/session/bind")
async def bind_session_skills(
    req: SkillSessionBindingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == req.session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="Session not found")
    enabled_skills = sorted(set(req.enabled_skills))
    disabled_skills = sorted(set(req.disabled_skills))
    account_ids = [item for item in enabled_skills if item.startswith("acct-")]
    if account_ids:
        allowed = set((await db.execute(select(UserSkillInstallation.installed_skill_id).where(
            UserSkillInstallation.user_id == current_user.id,
            UserSkillInstallation.tenant_id == session.tenant_id,
            UserSkillInstallation.workspace_id == session.workspace_id,
            UserSkillInstallation.status == "installed",
            UserSkillInstallation.installed_skill_id.in_(account_ids),
        ))).scalars().all())
        invalid = sorted(set(account_ids) - allowed)
        if invalid:
            raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="账户无权启用该 Skill")
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
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
