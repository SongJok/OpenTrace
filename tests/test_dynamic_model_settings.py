from __future__ import annotations

import pytest

from infra.model_settings.service import (
    decrypt_model_api_key,
    encrypt_model_api_key,
    mask_api_key,
    normalize_models,
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
    from infra.storage.model_settings import UserModelSettings

    constraints = {constraint.name for constraint in UserModelSettings.__table__.constraints}
    assert "uq_user_model_settings_scope" in constraints
    assert "api_key" not in UserModelSettings.__table__.columns
    assert "official_api_key_encrypted" in UserModelSettings.__table__.columns
    assert "relay_api_key_encrypted" in UserModelSettings.__table__.columns


def test_relay_environment_names_are_supported(monkeypatch):
    from infra.config.settings import LLMSettings

    monkeypatch.setenv("OTHER_LLM_MINSHORT_BASE_URL", "https://relay.example.com")
    monkeypatch.setenv("OTHER_LLM_MINSHORT_API_KEY", "sk-test")
    monkeypatch.setenv("OTHER_LLM_MODEL1", "gpt-5.6-sol")
    monkeypatch.setenv("OTHER_LLM_MODEL2", "kimi-k3-kimi")
    cfg = LLMSettings(_env_file=None)
    assert cfg.other_llm_minshort_base_url == "https://relay.example.com"
    assert cfg.other_llm_minshort_api_key == "sk-test"
    assert cfg.other_llm_model1 == "gpt-5.6-sol"
    assert cfg.other_llm_model2 == "kimi-k3-kimi"
