from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from gateway.api_gateway.routers.auth import get_current_user
from infra.errors import AppException, ErrorCodes
from infra.storage.models import User
from skills.store.marketplace import marketplace

router = APIRouter()

# user_id -> session_id -> {enabled_skills, disabled_skills}
_SESSION_SKILL_BINDINGS: dict[str, dict[str, dict[str, list[str]]]] = {}


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


@router.get("/skills")
async def list_skills(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    items = marketplace.list_installed()
    return {"items": [item.__dict__ for item in items], "user_id": current_user.id}


@router.post("/skills/install")
async def install_skill(req: SkillInstallRequest, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    try:
        installed = marketplace.install_from_git(req.git_url, req.ref)
    except Exception as exc:  # noqa: BLE001
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"install failed: {exc}")
    return {"installed": installed.__dict__, "user_id": current_user.id}


@router.post("/skills/create")
async def create_skill(req: SkillCreateRequest, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
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
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc))
    return {"skill": skill.__dict__, "user_id": current_user.id}


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    skill = marketplace.get_skill(skill_id)
    if skill is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")
    return {"skill": skill.__dict__, "user_id": current_user.id}


@router.post("/skills/{skill_id}/test")
async def test_skill(skill_id: str, req: SkillTestRequest, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    result = marketplace.test_skill(skill_id, req.test_input)
    return {"result": result, "user_id": current_user.id}


@router.post("/skills/uninstall")
async def uninstall_skill(req: SkillUninstallRequest, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    ok = marketplace.uninstall(req.skill_id)
    if not ok:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="skill not found")
    return {"removed": True, "skill_id": req.skill_id, "user_id": current_user.id}


@router.post("/skills/session/bind")
async def bind_session_skills(req: SkillSessionBindingRequest, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    by_user = _SESSION_SKILL_BINDINGS.setdefault(current_user.id, {})
    by_user[req.session_id] = {
        "enabled_skills": sorted(set(req.enabled_skills)),
        "disabled_skills": sorted(set(req.disabled_skills)),
    }
    return {
        "session_id": req.session_id,
        "enabled_skills": by_user[req.session_id]["enabled_skills"],
        "disabled_skills": by_user[req.session_id]["disabled_skills"],
    }


@router.get("/skills/session/{session_id}")
async def get_session_skills(session_id: str, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    by_user = _SESSION_SKILL_BINDINGS.setdefault(current_user.id, {})
    cfg = by_user.get(session_id, {"enabled_skills": [], "disabled_skills": []})
    return {
        "session_id": session_id,
        "enabled_skills": cfg.get("enabled_skills", []),
        "disabled_skills": cfg.get("disabled_skills", []),
    }
