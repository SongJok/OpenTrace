"""配置真相表契约 — 与 docs/CONFIG_TRUTH.md、docs/ENV_PROFILES.md 对齐。"""

from __future__ import annotations

import warnings

import pytest

from infra.config.settings import AppSettings, Settings, get_settings

MANAGED_ENV_SECRETS = {
    "app_secret_key": "test-app-secret",
    "jwt_secret": "test-jwt-secret",
    "data_secret_key": "test-data-secret",
}


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestConfigTruthDefaults:
    def test_app_and_gateway_port_model_defaults(self):
        assert AppSettings.model_fields["app_port"].default == 14100
        assert AppSettings.model_fields["gateway_port"].default == 14100

    def test_removed_v4_flag_is_not_part_of_runtime_settings(self):
        assert "kernel_orchestrator_v4_enabled" not in AppSettings.model_fields

    def test_agent_learning_auto_apply_default_false(self):
        assert AppSettings.model_fields["kernel_agent_learning_auto_apply"].default is False

    def test_rag_evidence_score_model_default(self):
        assert AppSettings.model_fields["rag_min_evidence_score"].default == pytest.approx(
            0.65, abs=0.01
        )

    def test_memory_fabric_primary_only_explicit_profile(self):
        s = Settings(
            app_env="development",
            kernel_memory_fabric_primary_only=True,
            gateway_port=14100,
            app_port=14100,
        )
        assert s.kernel_memory_fabric_primary_only is True


class TestStagingProfile:
    def test_staging_forces_fabric_primary(self):
        s = Settings(
            app_env="staging",
            kernel_memory_fabric_primary_only=False,
            gateway_port=14100,
            app_port=14100,
            **MANAGED_ENV_SECRETS,
        )
        assert s.kernel_memory_fabric_primary_only is True

    def test_staging_forces_cognitive_state_persist(self):
        s = Settings(
            app_env="staging",
            kernel_cognitive_state_persist_enabled=False,
            gateway_port=14100,
            app_port=14100,
            **MANAGED_ENV_SECRETS,
        )
        assert s.kernel_cognitive_state_persist_enabled is True

    def test_production_enables_fabric_and_world_state(self):
        s = Settings(
            app_env="production",
            kernel_memory_fabric_primary_only=False,
            kernel_world_state_persist_enabled=False,
            gateway_port=14100,
            app_port=14100,
            **MANAGED_ENV_SECRETS,
        )
        assert s.kernel_memory_fabric_primary_only is True
        assert s.kernel_world_state_persist_enabled is True

    def test_production_forces_agent_runtime_v3_strict(self):
        s = Settings(
            app_env="production",
            kernel_agent_runtime_v3_strict=False,
            kernel_unified_evidence_strict=False,
            gateway_port=14100,
            app_port=14100,
            **MANAGED_ENV_SECRETS,
        )
        assert s.kernel_agent_runtime_v3_strict is True
        assert s.kernel_unified_evidence_strict is True

    def test_staging_forces_agent_runtime_v3_strict(self):
        s = Settings(
            app_env="staging",
            kernel_agent_runtime_v3_strict=False,
            kernel_unified_evidence_strict=False,
            gateway_port=14100,
            app_port=14100,
            **MANAGED_ENV_SECRETS,
        )
        assert s.kernel_agent_runtime_v3_strict is True
        assert s.kernel_unified_evidence_strict is True

    def test_staging_enables_world_state_and_policy_fail_closed(self):
        s = Settings(
            app_env="staging",
            kernel_world_state_persist_enabled=False,
            kernel_policy_mutation_fail_closed=False,
            gateway_port=14100,
            app_port=14100,
            **MANAGED_ENV_SECRETS,
        )
        assert s.kernel_world_state_persist_enabled is True
        assert s.kernel_policy_mutation_fail_closed is True

    def test_staging_can_force_phase_strict(self):
        s = Settings(
            app_env="staging",
            kernel_runtime_phase_transition_strict=False,
            kernel_staging_phase_transition_strict=True,
            gateway_port=14100,
            app_port=14100,
            **MANAGED_ENV_SECRETS,
        )
        assert s.kernel_runtime_phase_transition_strict is True

    def test_managed_env_requires_runtime_secrets(self):
        with pytest.raises(ValueError, match="requires explicit non-placeholder secrets"):
            Settings(
                app_env="production",
                gateway_port=14100,
                app_port=14100,
                app_secret_key="change-me-in-production",
                jwt_secret="",
                data_secret_key="",
            )


class TestFlagGovernance:
    def test_default_settings_pass_flag_validation(self):
        from infra.config.flag_governance import validate_feature_flags

        s = Settings(app_env="development", gateway_port=14100, app_port=14100)
        result = validate_feature_flags(s)
        assert result.ok, result.violations

    def test_agent_runtime_v3_strict_requires_v3_enabled(self):
        from infra.config.flag_registry import validate_flag_dependencies

        s = Settings(
            app_env="development",
            gateway_port=14100,
            app_port=14100,
            kernel_agent_runtime_v3_enabled=False,
            kernel_agent_runtime_v3_strict=True,
        )
        violations = validate_flag_dependencies(s)
        assert any("kernel_agent_runtime_v3_strict_requires" in v for v in violations)

    def test_flag_registry_names_exist_on_settings(self):
        from infra.config.flag_registry import KERNEL_FLAG_REGISTRY

        fields = set(Settings.model_fields.keys())
        missing = [spec.name for spec in KERNEL_FLAG_REGISTRY if spec.name not in fields]
        assert missing == [], f"registry flags missing on Settings: {missing}"

    def test_env_example_documents_registry_flags(self):
        import re
        from pathlib import Path

        from infra.config.flag_registry import registry_env_keys

        root = Path(__file__).resolve().parents[1]
        env_text = (root / ".env.example").read_text(encoding="utf-8")
        present = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", env_text, re.M))
        missing = sorted(registry_env_keys() - present)
        assert missing == [], (
            "Add to .env.example or run: python scripts/sync_env_example_to_docs.py — "
            + ", ".join(missing)
        )


class TestGatewayPortWarning:
    def test_mismatched_gateway_port_warns_in_development(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Settings(app_env="development", app_port=14100, gateway_port=14101)
        msgs = [str(w.message) for w in caught]
        assert any("GATEWAY_PORT" in m and "APP_PORT" in m for m in msgs)

    def test_mismatched_gateway_port_fails_in_managed_env(self):
        with pytest.raises(ValueError, match="requires GATEWAY_PORT"):
            Settings(
                app_env="staging",
                app_port=14100,
                gateway_port=14101,
                **MANAGED_ENV_SECRETS,
            )
