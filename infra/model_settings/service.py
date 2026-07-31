"""动态模型配置解析、校验和密钥处理。"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.settings import settings
from infra.security.data_source_secrets import (
    decrypt_data_source_secret,
    encrypt_data_source_secret,
)
from infra.storage.model_settings import UserCustomModel, UserModelSettings
from model.model_gateway.runtime_config import RuntimeLLMProfile

ALLOWED_API_MODES = {"auto", "responses", "chat_completions"}
ALLOWED_SOURCES = {"free", "custom"}


@dataclass(frozen=True)
class EndpointDefaults:
    provider: str
    base_url: str
    model: str
    models: tuple[str, ...]
    api_mode: str
    api_key: str


def _unique_models(*values: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        model = str(value or "").strip()
        if model and model not in result:
            result.append(model)
    return tuple(result)


def free_defaults() -> EndpointDefaults:
    models = _unique_models(settings.free_llm_model1, settings.free_llm_model2)
    return EndpointDefaults(
        provider=settings.free_llm_minshort_provider,
        base_url=settings.free_llm_minshort_base_url,
        model=models[0] if models else "",
        models=models,
        api_mode=settings.free_llm_minshort_api_mode,
        api_key=settings.free_llm_minshort_api_key,
    )


def normalize_models(models: list[str] | tuple[str, ...], selected: str) -> tuple[str, ...]:
    normalized = _unique_models(*models, selected)
    if not normalized:
        raise ValueError("至少配置一个模型")
    if len(normalized) > 20:
        raise ValueError("模型候选最多 20 个")
    return normalized


def validate_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL 必须是有效的 HTTP(S) 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL 不允许包含凭据、查询参数或片段")
    hostname = parsed.hostname.lower()
    if parsed.path in {"", "/"}:
        normalized = f"{normalized}/v1"
    if not settings.dynamic_llm_allow_private_base_urls:
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError("Base URL 不允许指向本机地址")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise ValueError("Base URL 不允许指向内网或保留地址")
    return normalized


def mask_api_key(value: str) -> str:
    key = str(value or "")
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * min(12, len(key) - 8)}{key[-4:]}"


def encrypt_model_api_key(value: str) -> str:
    return encrypt_data_source_secret(value)


def decrypt_model_api_key(value: str | None) -> str:
    if not value:
        return ""
    return decrypt_data_source_secret(value)


def _free_profile(row: UserModelSettings | None) -> RuntimeLLMProfile | None:
    defaults = free_defaults()
    if not defaults.base_url or not defaults.model:
        return None
    selected = str(row.active_free_model or "").strip() if row else ""
    if selected not in defaults.models:
        selected = defaults.model
    return RuntimeLLMProfile(
        source="free",
        provider=defaults.provider,
        base_url=validate_base_url(defaults.base_url),
        api_key=defaults.api_key,
        model=selected,
        models=defaults.models,
        api_mode=defaults.api_mode,
    )


def _custom_profile(row: UserCustomModel) -> RuntimeLLMProfile:
    return RuntimeLLMProfile(
        source="custom",
        provider=row.provider,
        base_url=validate_base_url(row.base_url),
        api_key=decrypt_model_api_key(row.api_key_encrypted),
        model=row.model,
        models=(row.model,),
        api_mode=row.api_mode if row.api_mode in ALLOWED_API_MODES else "chat_completions",
    )


async def load_runtime_llm_profile(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> RuntimeLLMProfile | None:
    row = await db.scalar(
        select(UserModelSettings).where(
            UserModelSettings.user_id == user_id,
            UserModelSettings.tenant_id == tenant_id,
            UserModelSettings.workspace_id == workspace_id,
        )
    )
    if row is not None and row.active_source == "custom" and row.active_custom_model_id:
        custom = await db.scalar(
            select(UserCustomModel).where(
                UserCustomModel.id == row.active_custom_model_id,
                UserCustomModel.user_id == user_id,
                UserCustomModel.tenant_id == tenant_id,
                UserCustomModel.workspace_id == workspace_id,
            )
        )
        if custom is not None:
            return _custom_profile(custom)
    return _free_profile(row)
