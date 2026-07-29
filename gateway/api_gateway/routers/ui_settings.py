from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.errors import AppException, ErrorCodes
from infra.model_settings.service import (
    ALLOWED_API_MODES,
    decrypt_model_api_key,
    encrypt_model_api_key,
    environment_defaults,
    mask_api_key,
    normalize_models,
    relay_defaults,
    validate_base_url,
)
from infra.storage.database import db_session_dependency as get_db
from infra.storage.model_settings import UserModelSettings
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


class ModelEndpointPayload(BaseModel):
    provider: str = Field(default="", max_length=128)
    base_url: str = Field(default="", max_length=2048)
    api_key: str | None = Field(default=None, max_length=8192)
    clear_api_key: bool = False
    model: str = Field(default="", max_length=255)
    models: list[str] = Field(default_factory=list, max_length=20)
    api_mode: Literal["auto", "responses", "chat_completions"] = "chat_completions"


class ModelSettingsPayload(BaseModel):
    active_profile: Literal["environment", "official", "relay"] = "environment"
    official: ModelEndpointPayload
    relay: ModelEndpointPayload


class ModelSelectionPayload(BaseModel):
    profile: Literal["environment", "official", "relay"]
    model: str | None = Field(default=None, max_length=255)


def _endpoint_view(
    *,
    provider: str,
    base_url: str,
    model: str,
    models: list[str] | tuple[str, ...],
    api_mode: str,
    stored_encrypted: str | None,
    environment_key: str,
) -> dict:
    stored_key = decrypt_model_api_key(stored_encrypted)
    effective_key = stored_key or environment_key
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "models": list(normalize_models(list(models), model)) if model else list(models),
        "api_mode": api_mode,
        "has_api_key": bool(effective_key),
        "api_key_masked": mask_api_key(effective_key),
        "api_key_source": (
            "stored" if stored_key else ("environment" if environment_key else "missing")
        ),
    }


def _settings_view(row: UserModelSettings | None, *, tenant_id: str, workspace_id: str) -> dict:
    environment = environment_defaults()
    relay = relay_defaults()
    official_provider = (
        row.official_provider if row and row.official_provider else environment.provider
    )
    official_base_url = (
        row.official_base_url if row and row.official_base_url else environment.base_url
    )
    official_model = row.official_model if row and row.official_model else environment.model
    official_models = (
        row.official_models if row and row.official_models else list(environment.models)
    )
    official_api_mode = (
        row.official_api_mode if row and row.official_api_mode else environment.api_mode
    )
    relay_provider = row.relay_provider if row and row.relay_provider else relay.provider
    relay_base_url = row.relay_base_url if row and row.relay_base_url else relay.base_url
    relay_model = row.relay_model if row and row.relay_model else relay.model
    relay_models = row.relay_models if row and row.relay_models else list(relay.models)
    relay_api_mode = row.relay_api_mode if row and row.relay_api_mode else relay.api_mode
    return {
        "active_profile": row.active_profile if row else "environment",
        "scope": {"tenant_id": tenant_id, "workspace_id": workspace_id},
        "environment": _endpoint_view(
            provider=environment.provider,
            base_url=environment.base_url,
            model=environment.model,
            models=environment.models,
            api_mode=environment.api_mode,
            stored_encrypted=None,
            environment_key=environment.api_key,
        ),
        "official": _endpoint_view(
            provider=official_provider,
            base_url=official_base_url,
            model=official_model,
            models=official_models,
            api_mode=official_api_mode,
            stored_encrypted=row.official_api_key_encrypted if row else None,
            environment_key=environment.api_key,
        ),
        "relay": _endpoint_view(
            provider=relay_provider,
            base_url=relay_base_url,
            model=relay_model,
            models=relay_models,
            api_mode=relay_api_mode,
            stored_encrypted=row.relay_api_key_encrypted if row else None,
            environment_key=relay.api_key,
        ),
    }


def _validated_endpoint(
    payload: ModelEndpointPayload, *, required: bool = True
) -> tuple[str, tuple[str, ...]]:
    if not required and not payload.base_url.strip() and not payload.model.strip():
        return "", tuple()
    try:
        base_url = validate_base_url(payload.base_url)
        models = normalize_models(payload.models, payload.model)
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    if payload.api_mode not in ALLOWED_API_MODES:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="不支持的 API 模式")
    return base_url, models


@router.get("/users/model-settings")
async def get_model_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    scope = build_tenant_metadata(request, user_id=current_user.id)
    tenant_id = str(scope.get("tenant_id") or "default")
    workspace_id = str(scope.get("workspace_id") or "default")
    row = await db.scalar(
        select(UserModelSettings).where(
            UserModelSettings.user_id == current_user.id,
            UserModelSettings.tenant_id == tenant_id,
            UserModelSettings.workspace_id == workspace_id,
        )
    )
    return _settings_view(row, tenant_id=tenant_id, workspace_id=workspace_id)


@router.patch("/users/model-settings")
async def patch_model_settings(
    request: Request,
    req: ModelSettingsPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    scope = build_tenant_metadata(request, user_id=current_user.id)
    tenant_id = str(scope.get("tenant_id") or "default")
    workspace_id = str(scope.get("workspace_id") or "default")
    official_base_url, official_models = _validated_endpoint(
        req.official, required=req.active_profile == "official"
    )
    relay_base_url, relay_models = _validated_endpoint(
        req.relay, required=req.active_profile == "relay"
    )
    row = await db.scalar(
        select(UserModelSettings).where(
            UserModelSettings.user_id == current_user.id,
            UserModelSettings.tenant_id == tenant_id,
            UserModelSettings.workspace_id == workspace_id,
        )
    )
    if row is None:
        row = UserModelSettings(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        db.add(row)
        await db.flush()

    row.active_profile = req.active_profile
    row.official_provider = req.official.provider.strip()
    row.official_base_url = official_base_url
    row.official_model = req.official.model.strip()
    row.official_models = list(official_models)
    row.official_api_mode = req.official.api_mode
    row.relay_provider = req.relay.provider.strip()
    row.relay_base_url = relay_base_url
    row.relay_model = req.relay.model.strip()
    row.relay_models = list(relay_models)
    row.relay_api_mode = req.relay.api_mode

    if req.official.clear_api_key:
        row.official_api_key_encrypted = None
    elif req.official.api_key is not None and req.official.api_key.strip():
        row.official_api_key_encrypted = encrypt_model_api_key(req.official.api_key.strip())
    if req.relay.clear_api_key:
        row.relay_api_key_encrypted = None
    elif req.relay.api_key is not None and req.relay.api_key.strip():
        row.relay_api_key_encrypted = encrypt_model_api_key(req.relay.api_key.strip())

    environment = environment_defaults()
    relay_environment = relay_defaults()
    if req.active_profile == "official":
        effective_key = decrypt_model_api_key(row.official_api_key_encrypted) or environment.api_key
        if not effective_key:
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="原始服务尚未配置 API Key")
    elif req.active_profile == "relay":
        effective_key = (
            decrypt_model_api_key(row.relay_api_key_encrypted) or relay_environment.api_key
        )
        if not effective_key:
            raise AppException(
                ErrorCodes.PARAM_INVALID.code, message="第三方中转站尚未配置 API Key"
            )

    await db.commit()
    return _settings_view(row, tenant_id=tenant_id, workspace_id=workspace_id)


@router.patch("/users/model-settings/selection")
async def select_active_model(
    request: Request,
    req: ModelSelectionPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """点击模型后原子切换；不覆盖设置页中尚未保存的端点编辑。"""
    scope = build_tenant_metadata(request, user_id=current_user.id)
    tenant_id = str(scope.get("tenant_id") or "default")
    workspace_id = str(scope.get("workspace_id") or "default")
    row = await db.scalar(
        select(UserModelSettings).where(
            UserModelSettings.user_id == current_user.id,
            UserModelSettings.tenant_id == tenant_id,
            UserModelSettings.workspace_id == workspace_id,
        )
    )
    if req.profile == "environment":
        if row is not None:
            row.active_profile = "environment"
            await db.commit()
        return _settings_view(row, tenant_id=tenant_id, workspace_id=workspace_id)

    if row is None:
        row = UserModelSettings(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        db.add(row)
        await db.flush()

    current = _settings_view(row, tenant_id=tenant_id, workspace_id=workspace_id)
    endpoint = current[req.profile]
    selected_model = str(req.model or endpoint.get("model") or "").strip()
    if not selected_model or selected_model not in set(endpoint.get("models") or []):
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="所选模型不在当前服务的候选列表中，请先保存模型候选。",
        )
    if not endpoint.get("has_api_key"):
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message="当前模型服务尚未配置 API Key。",
        )
    try:
        normalized_base_url = validate_base_url(str(endpoint.get("base_url") or ""))
    except ValueError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc

    row.active_profile = req.profile
    if req.profile == "official":
        row.official_provider = str(endpoint.get("provider") or "")
        row.official_base_url = normalized_base_url
        row.official_model = selected_model
        row.official_models = list(endpoint.get("models") or [])
        row.official_api_mode = str(endpoint.get("api_mode") or "auto")
    else:
        row.relay_provider = str(endpoint.get("provider") or "")
        row.relay_base_url = normalized_base_url
        row.relay_model = selected_model
        row.relay_models = list(endpoint.get("models") or [])
        row.relay_api_mode = str(endpoint.get("api_mode") or "chat_completions")
    await db.commit()
    return _settings_view(row, tenant_id=tenant_id, workspace_id=workspace_id)
