from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.model_settings.service import (
    ALLOWED_API_MODES,
    decrypt_model_api_key,
    encrypt_model_api_key,
    free_defaults,
    mask_api_key,
    validate_base_url,
)
from infra.storage.database import db_session_dependency as get_db
from infra.storage.model_settings import UserCustomModel, UserModelSettings
from infra.storage.models import User, UserUiSettings

router = APIRouter()


class UiSettingsPayload(BaseModel):
    reasoning_default_expanded: bool = True
    graph_default_expanded: bool = True
    dag_default_expanded: bool = True
    execution_graph_default_expanded: bool = True
    decision_trace_default_expanded: bool = True
    flow_cards_default_expanded: bool = True
    theme_mode: str = "system"
    theme_accent: str = "blue"


@router.get("/users/ui-settings")
async def get_ui_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UiSettingsPayload:
    result = await db.execute(
        select(UserUiSettings).where(UserUiSettings.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return UiSettingsPayload()
    return UiSettingsPayload(
        reasoning_default_expanded=bool(row.reasoning_default_expanded),
        graph_default_expanded=bool(row.graph_default_expanded),
        dag_default_expanded=bool(row.dag_default_expanded),
        execution_graph_default_expanded=bool(row.execution_graph_default_expanded),
        decision_trace_default_expanded=bool(row.decision_trace_default_expanded),
        flow_cards_default_expanded=bool(row.flow_cards_default_expanded),
        theme_mode=row.theme_mode,
        theme_accent=row.theme_accent,
    )


@router.patch("/users/ui-settings")
async def patch_ui_settings(
    req: UiSettingsPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UiSettingsPayload:
    result = await db.execute(
        select(UserUiSettings).where(UserUiSettings.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    if not row:
        row = UserUiSettings(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            reasoning_default_expanded=req.reasoning_default_expanded,
            graph_default_expanded=req.graph_default_expanded,
            dag_default_expanded=req.dag_default_expanded,
            execution_graph_default_expanded=req.execution_graph_default_expanded,
            decision_trace_default_expanded=req.decision_trace_default_expanded,
            flow_cards_default_expanded=req.flow_cards_default_expanded,
            theme_mode=req.theme_mode,
            theme_accent=req.theme_accent,
        )
        db.add(row)
    else:
        row.reasoning_default_expanded = req.reasoning_default_expanded
        row.graph_default_expanded = req.graph_default_expanded
        row.dag_default_expanded = req.dag_default_expanded
        row.execution_graph_default_expanded = req.execution_graph_default_expanded
        row.decision_trace_default_expanded = req.decision_trace_default_expanded
        row.flow_cards_default_expanded = req.flow_cards_default_expanded
        row.theme_mode = req.theme_mode
        row.theme_accent = req.theme_accent
    await db.commit()
    return UiSettingsPayload(
        reasoning_default_expanded=bool(req.reasoning_default_expanded),
        graph_default_expanded=bool(req.graph_default_expanded),
        dag_default_expanded=bool(req.dag_default_expanded),
        execution_graph_default_expanded=bool(req.execution_graph_default_expanded),
        decision_trace_default_expanded=bool(req.decision_trace_default_expanded),
        flow_cards_default_expanded=bool(req.flow_cards_default_expanded),
        theme_mode=req.theme_mode,
        theme_accent=req.theme_accent,
    )


class CustomModelCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="自定义 / Custom", max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(min_length=1, max_length=8192)
    model: str = Field(min_length=1, max_length=255)
    api_mode: Literal["auto", "responses", "chat_completions"] = "chat_completions"


class CustomModelUpdatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="自定义 / Custom", max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, max_length=8192)
    model: str = Field(min_length=1, max_length=255)
    api_mode: Literal["auto", "responses", "chat_completions"] = "chat_completions"


class ModelSelectionPayload(BaseModel):
    source: Literal["free", "custom"]
    model: str | None = Field(default=None, max_length=255)
    custom_model_id: str | None = Field(default=None, max_length=36)


def _scope(request: Request, user_id: str) -> tuple[str, str]:
    metadata = build_tenant_metadata(request, user_id=user_id)
    return (
        str(metadata.get("tenant_id") or "default"),
        str(metadata.get("workspace_id") or "default"),
    )


def _custom_model_view(row: UserCustomModel) -> dict:
    api_key = decrypt_model_api_key(row.api_key_encrypted)
    return {
        "id": row.id,
        "name": row.name,
        "provider": row.provider,
        "base_url": row.base_url,
        "model": row.model,
        "api_mode": row.api_mode,
        "has_api_key": bool(api_key),
        "api_key_masked": mask_api_key(api_key),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _settings_view(
    row: UserModelSettings | None,
    custom_models: list[UserCustomModel],
    *,
    tenant_id: str,
    workspace_id: str,
) -> dict:
    free = free_defaults()
    free_model = str(row.active_free_model or "").strip() if row else ""
    if free_model not in free.models:
        free_model = free.model
    custom_by_id = {item.id: item for item in custom_models}
    active_custom = custom_by_id.get(row.active_custom_model_id) if row else None
    active_source = "custom" if row and row.active_source == "custom" and active_custom else "free"
    active_model = active_custom.model if active_custom else free_model
    return {
        "active_selection": {
            "source": active_source,
            "model": active_model,
            "custom_model_id": active_custom.id if active_custom else None,
        },
        "scope": {"tenant_id": tenant_id, "workspace_id": workspace_id},
        "free": {
            "provider": free.provider,
            "base_url": free.base_url,
            "models": list(free.models),
            "api_mode": free.api_mode,
            "has_api_key": bool(free.api_key),
        },
        "custom_models": [_custom_model_view(item) for item in custom_models],
    }


def _validated_custom_payload(
    payload: CustomModelCreatePayload | CustomModelUpdatePayload,
) -> tuple[str, str, str, str]:
    name = payload.name.strip()
    provider = payload.provider.strip() or "自定义 / Custom"
    model = payload.model.strip()
    if not name or not model:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="名称和模型名称不能为空")
    try:
        base_url = validate_base_url(payload.base_url)
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    if payload.api_mode not in ALLOWED_API_MODES:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="不支持的 API 模式")
    return name, provider, base_url, model


async def _get_settings_row(
    db: AsyncSession, *, user_id: str, tenant_id: str, workspace_id: str
) -> UserModelSettings | None:
    return await db.scalar(
        select(UserModelSettings).where(
            UserModelSettings.user_id == user_id,
            UserModelSettings.tenant_id == tenant_id,
            UserModelSettings.workspace_id == workspace_id,
        )
    )


async def _get_custom_models(
    db: AsyncSession, *, user_id: str, tenant_id: str, workspace_id: str
) -> list[UserCustomModel]:
    result = await db.scalars(
        select(UserCustomModel)
        .where(
            UserCustomModel.user_id == user_id,
            UserCustomModel.tenant_id == tenant_id,
            UserCustomModel.workspace_id == workspace_id,
        )
        .order_by(UserCustomModel.created_at.asc(), UserCustomModel.id.asc())
    )
    return list(result.all())


async def _get_or_create_settings_row(
    db: AsyncSession, *, user_id: str, tenant_id: str, workspace_id: str
) -> UserModelSettings:
    row = await _get_settings_row(
        db, user_id=user_id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if row is None:
        row = UserModelSettings(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            active_source="free",
        )
        db.add(row)
        await db.flush()
    return row


async def _get_scoped_custom_model(
    db: AsyncSession,
    *,
    model_id: str,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> UserCustomModel:
    row = await db.scalar(
        select(UserCustomModel).where(
            UserCustomModel.id == model_id,
            UserCustomModel.user_id == user_id,
            UserCustomModel.tenant_id == tenant_id,
            UserCustomModel.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message="自定义模型不存在")
    return row


async def _ensure_unique_custom_name(
    db: AsyncSession,
    *,
    name: str,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
    exclude_id: str | None = None,
) -> None:
    query = select(UserCustomModel.id).where(
        UserCustomModel.user_id == user_id,
        UserCustomModel.tenant_id == tenant_id,
        UserCustomModel.workspace_id == workspace_id,
        UserCustomModel.name == name,
    )
    if exclude_id:
        query = query.where(UserCustomModel.id != exclude_id)
    if await db.scalar(query):
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="自定义模型名称已存在")


@router.get("/users/model-settings")
async def get_model_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user.id)
    row = await _get_settings_row(
        db, user_id=current_user.id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    custom_models = await _get_custom_models(
        db, user_id=current_user.id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    return _settings_view(row, custom_models, tenant_id=tenant_id, workspace_id=workspace_id)


@router.post("/users/model-settings/custom-models", status_code=201)
async def create_custom_model(
    request: Request,
    req: CustomModelCreatePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user.id)
    name, provider, base_url, model = _validated_custom_payload(req)
    api_key = req.api_key.strip()
    if not api_key:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="API Key 不能为空")
    count = await db.scalar(
        select(func.count(UserCustomModel.id)).where(
            UserCustomModel.user_id == current_user.id,
            UserCustomModel.tenant_id == tenant_id,
            UserCustomModel.workspace_id == workspace_id,
        )
    )
    if int(count or 0) >= 20:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="每个工作区最多添加 20 个模型")
    await _ensure_unique_custom_name(
        db,
        name=name,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    row = UserCustomModel(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        name=name,
        provider=provider,
        base_url=base_url,
        api_key_encrypted=encrypt_model_api_key(api_key),
        model=model,
        api_mode=req.api_mode,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _custom_model_view(row)


@router.patch("/users/model-settings/custom-models/{model_id}")
async def update_custom_model(
    model_id: str,
    request: Request,
    req: CustomModelUpdatePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user.id)
    row = await _get_scoped_custom_model(
        db,
        model_id=model_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    name, provider, base_url, model = _validated_custom_payload(req)
    await _ensure_unique_custom_name(
        db,
        name=name,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        exclude_id=row.id,
    )
    row.name = name
    row.provider = provider
    row.base_url = base_url
    row.model = model
    row.api_mode = req.api_mode
    if req.api_key is not None:
        api_key = req.api_key.strip()
        if not api_key:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="API Key 不能为空")
        row.api_key_encrypted = encrypt_model_api_key(api_key)
    await db.commit()
    await db.refresh(row)
    return _custom_model_view(row)


@router.delete("/users/model-settings/custom-models/{model_id}")
async def delete_custom_model(
    model_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id, workspace_id = _scope(request, current_user.id)
    custom = await _get_scoped_custom_model(
        db,
        model_id=model_id,
        user_id=current_user.id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    settings_row = await _get_settings_row(
        db, user_id=current_user.id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if settings_row and settings_row.active_custom_model_id == custom.id:
        settings_row.active_source = "free"
        settings_row.active_custom_model_id = None
    await db.delete(custom)
    await db.commit()
    return {"deleted": True, "id": model_id}


@router.patch("/users/model-settings/selection")
async def select_active_model(
    request: Request,
    req: ModelSelectionPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """原子切换下一次 Response 使用的免费或用户自定义模型。"""
    tenant_id, workspace_id = _scope(request, current_user.id)
    row = await _get_or_create_settings_row(
        db, user_id=current_user.id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if req.source == "free":
        defaults = free_defaults()
        selected = str(req.model or defaults.model).strip()
        if selected not in defaults.models:
            raise AppException(
                ErrorCodes.PARAM_INVALID.code, message="所选模型不在通用免费模型列表中"
            )
        if not defaults.api_key:
            raise AppException(
                ErrorCodes.PARAM_INVALID.code, message="通用免费模型尚未配置 API Key"
            )
        row.active_source = "free"
        row.active_free_model = selected
        row.active_custom_model_id = None
    else:
        if not req.custom_model_id:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="请选择自定义模型")
        custom = await _get_scoped_custom_model(
            db,
            model_id=req.custom_model_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if not decrypt_model_api_key(custom.api_key_encrypted):
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="自定义模型缺少 API Key")
        row.active_source = "custom"
        row.active_custom_model_id = custom.id
    await db.commit()
    custom_models = await _get_custom_models(
        db, user_id=current_user.id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    return _settings_view(row, custom_models, tenant_id=tenant_id, workspace_id=workspace_id)
