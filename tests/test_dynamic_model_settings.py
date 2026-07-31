from __future__ import annotations

import pytest

from infra.model_settings.service import (
    decrypt_model_api_key,
    encrypt_model_api_key,
    free_defaults,
    load_runtime_llm_profile,
    mask_api_key,
    normalize_models,
    snapshot_runtime_llm_selection,
    validate_base_url,
)
from model.model_gateway.gateway import LLMRole, ModelGateway, _build_config
from model.model_gateway.runtime_config import RuntimeLLMProfile, use_runtime_llm_profile


def test_model_api_key_is_encrypted_and_masked(monkeypatch):
    from infra.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "data_secret_key", "dynamic-model-test-secret")
    plain = "sk-super-secret-model-key"
    encrypted = encrypt_model_api_key(plain)

    assert plain not in encrypted
    assert decrypt_model_api_key(encrypted) == plain
    assert mask_api_key(plain).startswith("sk-s")
    assert mask_api_key(plain).endswith("-key")
    assert plain not in mask_api_key(plain)


def test_runtime_profile_overrides_all_text_roles_and_restores_environment():
    environment = _build_config(LLMRole.PLANNING)
    profile = RuntimeLLMProfile(
        source="relay",
        provider="relay",
        base_url="https://relay.example.com/v1",
        api_key="sk-test",
        model="gpt-5.6-sol",
        models=("gpt-5.6-sol", "kimi-k3-kimi"),
        api_mode="chat_completions",
    )

    with use_runtime_llm_profile(profile):
        planning = _build_config(LLMRole.PLANNING)
        query_adapter = ModelGateway()._get_adapter(LLMRole.QUERY, "qwen3.7-max")
        selected_adapter = ModelGateway()._get_adapter(LLMRole.QUERY, "kimi-k3-kimi")
        vision = _build_config(LLMRole.VISION)

        assert planning.base_url == profile.base_url
        assert planning.model == profile.model
        assert query_adapter.config.model == "gpt-5.6-sol"
        assert selected_adapter.config.model == "kimi-k3-kimi"
        assert vision.base_url != profile.base_url

    assert _build_config(LLMRole.PLANNING) == environment


def test_model_endpoint_validation_blocks_private_network_by_default(monkeypatch):
    from infra.model_settings import service

    monkeypatch.setattr(service.settings, "dynamic_llm_allow_private_base_urls", False)
    assert validate_base_url("https://relay.example.com/v1/") == "https://relay.example.com/v1"
    assert validate_base_url("https://relay.example.com") == "https://relay.example.com/v1"
    with pytest.raises(ValueError, match="内网|本机"):
        validate_base_url("http://127.0.0.1:8000/v1")
    with pytest.raises(ValueError, match="本机"):
        validate_base_url("http://localhost:11434/v1")


def test_model_candidates_are_deduplicated_and_keep_selected_model():
    assert normalize_models(["a", "b", "a"], "b") == ("a", "b")
    assert normalize_models(["a"], "c") == ("a", "c")


def test_model_settings_table_is_scoped_and_secret_is_never_plaintext():
    from infra.storage.model_settings import UserCustomModel, UserModelSettings

    constraints = {constraint.name for constraint in UserModelSettings.__table__.constraints}
    assert "uq_user_model_settings_scope" in constraints
    assert "api_key" not in UserModelSettings.__table__.columns
    assert "official_api_key_encrypted" in UserModelSettings.__table__.columns
    assert "relay_api_key_encrypted" in UserModelSettings.__table__.columns
    custom_constraints = {constraint.name for constraint in UserCustomModel.__table__.constraints}
    assert "uq_user_custom_models_scope_name" in custom_constraints
    assert "api_key" not in UserCustomModel.__table__.columns
    assert "api_key_encrypted" in UserCustomModel.__table__.columns


def test_free_model_environment_names_are_supported(monkeypatch):
    from infra.config.settings import LLMSettings

    monkeypatch.setenv("FREE_LLM_MINSHORT_BASE_URL", "https://free.example.com")
    monkeypatch.setenv("FREE_LLM_MINSHORT_API_KEY", "sk-test")
    monkeypatch.setenv("FREE_LLM_MODEL1", "glm-5.2-free")
    monkeypatch.setenv("FREE_LLM_MODEL2", "deepseek-v4-pro-free")
    cfg = LLMSettings(_env_file=None)
    assert cfg.free_llm_minshort_base_url == "https://free.example.com"
    assert cfg.free_llm_minshort_api_key == "sk-test"
    assert cfg.free_llm_model1 == "glm-5.2-free"
    assert cfg.free_llm_model2 == "deepseek-v4-pro-free"


def test_free_defaults_expose_only_the_two_configured_models(monkeypatch):
    from infra.model_settings import service

    monkeypatch.setattr(service.settings, "free_llm_model1", "glm-5.2-free")
    monkeypatch.setattr(service.settings, "free_llm_model2", "deepseek-v4-pro-free")
    defaults = free_defaults()
    assert defaults.models == ("glm-5.2-free", "deepseek-v4-pro-free")
    assert defaults.model == "glm-5.2-free"


@pytest.mark.asyncio
async def test_runtime_uses_selected_free_model(monkeypatch):
    from unittest.mock import AsyncMock

    from infra.model_settings import service
    from infra.storage.model_settings import UserModelSettings

    monkeypatch.setattr(service.settings, "free_llm_minshort_base_url", "https://free.example")
    monkeypatch.setattr(service.settings, "free_llm_minshort_api_key", "sk-free")
    monkeypatch.setattr(service.settings, "free_llm_model1", "glm-5.2-free")
    monkeypatch.setattr(service.settings, "free_llm_model2", "deepseek-v4-pro-free")
    row = UserModelSettings(
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        active_source="free",
        active_free_model="deepseek-v4-pro-free",
    )
    db = AsyncMock()
    db.scalar.return_value = row

    profile = await load_runtime_llm_profile(
        db, user_id="user-1", tenant_id="tenant-1", workspace_id="workspace-1"
    )

    assert profile is not None
    assert profile.source == "free"
    assert profile.model == "deepseek-v4-pro-free"
    assert profile.models == ("glm-5.2-free", "deepseek-v4-pro-free")


@pytest.mark.asyncio
async def test_response_snapshot_keeps_free_model_after_user_switches(monkeypatch):
    from unittest.mock import AsyncMock

    from infra.model_settings import service

    monkeypatch.setattr(service.settings, "free_llm_minshort_base_url", "https://free.example")
    monkeypatch.setattr(service.settings, "free_llm_minshort_api_key", "sk-free")
    monkeypatch.setattr(service.settings, "free_llm_model1", "glm-5.2-free")
    monkeypatch.setattr(service.settings, "free_llm_model2", "deepseek-v4-pro-free")
    db = AsyncMock()

    profile = await load_runtime_llm_profile(
        db,
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        selection={
            "version": 1,
            "source": "free",
            "model": "glm-5.2-free",
            "custom_model_id": None,
        },
    )

    assert profile is not None
    assert profile.model == "glm-5.2-free"
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_custom_model_is_scoped_and_decrypted(monkeypatch):
    from unittest.mock import AsyncMock

    from infra.config.settings import get_settings
    from infra.storage.model_settings import UserCustomModel, UserModelSettings

    monkeypatch.setattr(get_settings(), "data_secret_key", "custom-model-runtime-secret")
    settings_row = UserModelSettings(
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        active_source="custom",
        active_custom_model_id="custom-1",
    )
    custom = UserCustomModel(
        id="custom-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        name="开发模型",
        provider="Custom",
        base_url="https://custom.example/v1",
        api_key_encrypted=encrypt_model_api_key("sk-custom"),
        model="custom-model",
        api_mode="responses",
    )
    db = AsyncMock()
    db.scalar.side_effect = [settings_row, custom]

    profile = await load_runtime_llm_profile(
        db, user_id="user-1", tenant_id="tenant-1", workspace_id="workspace-1"
    )

    assert profile is not None
    assert profile.source == "custom"
    assert profile.api_key == "sk-custom"
    assert profile.model == "custom-model"
    custom_query = str(db.scalar.await_args_list[1].args[0])
    assert "user_custom_models.user_id" in custom_query
    assert "user_custom_models.tenant_id" in custom_query
    assert "user_custom_models.workspace_id" in custom_query


@pytest.mark.asyncio
async def test_response_snapshot_uses_original_scoped_custom_model(monkeypatch):
    from unittest.mock import AsyncMock

    from infra.config.settings import get_settings
    from infra.storage.model_settings import UserCustomModel

    monkeypatch.setattr(get_settings(), "data_secret_key", "custom-model-snapshot-secret")
    custom = UserCustomModel(
        id="custom-original",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        name="原模型",
        provider="Custom",
        base_url="https://custom.example/v1",
        api_key_encrypted=encrypt_model_api_key("sk-original"),
        model="original-model",
        api_mode="responses",
    )
    db = AsyncMock()
    db.scalar.return_value = custom

    profile = await load_runtime_llm_profile(
        db,
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        selection={
            "version": 1,
            "source": "custom",
            "model": "original-model",
            "custom_model_id": "custom-original",
        },
    )

    assert profile is not None
    assert profile.model == "original-model"
    assert profile.api_key == "sk-original"
    custom_query = str(db.scalar.await_args.args[0])
    assert "user_custom_models.user_id" in custom_query
    assert "user_custom_models.tenant_id" in custom_query
    assert "user_custom_models.workspace_id" in custom_query


@pytest.mark.asyncio
async def test_model_selection_snapshot_contains_no_secret(monkeypatch):
    from unittest.mock import AsyncMock

    from infra.model_settings import service
    from infra.storage.model_settings import UserModelSettings

    monkeypatch.setattr(service.settings, "free_llm_minshort_api_key", "sk-never-persist")
    monkeypatch.setattr(service.settings, "free_llm_model1", "glm-5.2-free")
    monkeypatch.setattr(service.settings, "free_llm_model2", "deepseek-v4-pro-free")
    settings_row = UserModelSettings(
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        active_source="free",
        active_free_model="deepseek-v4-pro-free",
    )
    db = AsyncMock()
    db.scalar.return_value = settings_row

    snapshot = await snapshot_runtime_llm_selection(
        db,
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )

    assert snapshot == {
        "version": 1,
        "source": "free",
        "model": "deepseek-v4-pro-free",
        "custom_model_id": None,
    }
    assert "key" not in str(snapshot).lower()


def test_model_selection_endpoint_is_atomic_and_scoped():
    from pathlib import Path

    source = Path("gateway/api_gateway/routers/ui_settings.py").read_text(encoding="utf-8")
    assert '@router.patch("/users/model-settings/selection")' in source
    assert "UserModelSettings.user_id == user_id" in source
    assert "UserModelSettings.tenant_id == tenant_id" in source
    assert "UserModelSettings.workspace_id == workspace_id" in source
    assert '@router.post("/users/model-settings/custom-models"' in source
    assert '@router.patch("/users/model-settings/custom-models/{model_id}")' in source
    assert '@router.delete("/users/model-settings/custom-models/{model_id}")' in source
    assert "UserCustomModel.user_id == user_id" in source
    assert "UserCustomModel.tenant_id == tenant_id" in source
    assert "UserCustomModel.workspace_id == workspace_id" in source
    assert "所选模型不在通用免费模型列表中" in source


def test_kimi_k3_temperature_is_normalized_for_relay_compatibility():
    from model.llm_adapter.base import LLMConfig
    from model.llm_adapter.openai_adapter import OpenAICompatibleAdapter

    kimi = OpenAICompatibleAdapter(
        LLMConfig(
            provider="relay",
            model="kimi-k3-kimi",
            base_url="https://relay.example/v1",
            api_key="sk-test",
            temperature=0.7,
        )
    )
    other = OpenAICompatibleAdapter(
        LLMConfig(
            provider="relay",
            model="gpt-5.6-sol",
            base_url="https://relay.example/v1",
            api_key="sk-test",
            temperature=0.7,
        )
    )

    assert kimi._request_temperature({}) == 1.0
    assert kimi._request_temperature({"temperature": 0.2}) == 1.0
    assert other._request_temperature({}) == 0.7
