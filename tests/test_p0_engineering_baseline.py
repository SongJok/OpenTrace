"""P0 产品化基线：架构、配置、依赖、迁移和 CI 治理。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.check_architecture_manifest import validate_manifest
from scripts.check_migration_policy import validate_policy

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_architecture_manifest_matches_online_implementation() -> None:
    assert validate_manifest() == []


def test_migration_history_is_frozen_and_single_head() -> None:
    assert validate_policy() == []


def test_product_maturity_uses_alpha_beta_ga_only() -> None:
    manifest = yaml.safe_load(
        (ROOT / "docs/architecture/runtime_manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["product"]["maturity"] == "Beta"
    assert manifest["product"]["maturity_scale"] == ["Alpha", "Beta", "GA"]
    maturity = (ROOT / "docs/CAPABILITY_MATURITY.md").read_text(encoding="utf-8")
    assert "**生产**" not in maturity
    assert "compatibility / experimental" in maturity


def test_capability_profiles_are_bounded_and_deterministic() -> None:
    from agents.bootstrap import agent_types_for_profile
    from infra.config.settings import AppSettings

    annotation = AppSettings.model_fields["capability_profile"].annotation
    profiles = set(annotation.__args__)
    assert profiles == {"core", "data", "knowledge", "data_knowledge"}
    assert len(profiles) <= 5
    assert agent_types_for_profile("core") == frozenset({"tool", "skills", "rules"})
    assert "data" in agent_types_for_profile("data")
    assert "rag" in agent_types_for_profile("knowledge")
    assert {"data", "rag", "web_intelligence", "vision"}.issubset(
        agent_types_for_profile("data_knowledge")
    )
    assert agent_types_for_profile("unknown") == frozenset()


def test_public_high_impact_flags_are_reduced_and_governed() -> None:
    from infra.config.flag_registry import KERNEL_FLAG_REGISTRY, validate_registry_governance

    assert len(KERNEL_FLAG_REGISTRY) <= 8
    assert validate_registry_governance() == []
    experimental = [spec for spec in KERNEL_FLAG_REGISTRY if spec.phase == "experimental"]
    assert experimental
    assert all(spec.owner and spec.introduced for spec in experimental)
    assert all(spec.exit_criteria and spec.remove_by for spec in experimental)


def test_python_and_frontend_dependency_locks_are_declared() -> None:
    for relative_path in (
        "uv.lock",
        "requirements.lock",
        "requirements-dev.lock",
        "frontend/package-lock.json",
    ):
        path = ROOT / relative_path
        assert path.exists() and path.stat().st_size > 100

    dockerfile = (ROOT / "deploy/docker/Dockerfile").read_text(encoding="utf-8")
    assert "COPY requirements.lock" in dockerfile
    assert "--require-hashes -r requirements.lock" in dockerfile
    lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8").lower()
    assert "aiomysql==" in lock_text
    assert "pyjwt==" in lock_text
    assert "asyncmy==" not in lock_text
    assert "ecdsa==" not in lock_text


def test_frozen_future_named_migrations_remain_explicitly_immutable() -> None:
    policy = json.loads((ROOT / "alembic/migration_policy.json").read_text(encoding="utf-8"))
    frozen_files = {entry["file"] for entry in policy["frozen_migrations"]}
    # 2026-07-25 至 2026-08-03 的已提交文件不重命名，只冻结校验和。
    future_named = {
        f"alembic/versions/202607{day:02d}_{suffix}.py"
        for day, suffix in [
            (25, "normalize_vector_columns"),
            (26, "add_user_memory_score"),
            (27, "project_knowledge_scope"),
            (28, "active_alerts"),
            (29, "skillhub_acl_orchestration"),
            (30, "data_source_schema_embedding"),
            (31, "memory_constitution"),
        ]
    } | {
        "alembic/versions/20260801_memory_constitution_concurrency.py",
        "alembic/versions/20260802_chat_constitution.py",
        "alembic/versions/20260803_chatgpt_five_pillars.py",
    }
    assert future_named.issubset(frozen_files)


def test_migration_revision_parsers_support_current_alembic_template(tmp_path: Path) -> None:
    from scripts.check_migration_policy import _revision as policy_revision
    from scripts.freeze_migration import _revision as freeze_revision

    migration = tmp_path / "r0001_example.py"
    migration.write_text('revision: str = "r0001_example"\n', encoding="utf-8")

    assert policy_revision(migration) == "r0001_example"
    assert freeze_revision(migration) == "r0001_example"


def test_ci_has_fast_full_and_security_gates() -> None:
    fast = (ROOT / ".github/workflows/ci-fast.yml").read_text(encoding="utf-8")
    fast_entry = (ROOT / "scripts/ci_fast.sh").read_text(encoding="utf-8")
    full = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    security = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
    for command in (
        "uv lock --check",
        "black --check",
        "ruff check",
        "mypy",
        "npm test",
        "npm run build",
    ):
        assert command in fast_entry
    assert "scripts/ci_fast.sh --backend" in fast
    assert "scripts/ci_fast.sh --frontend" in fast
    assert "timeout-minutes: 12" in fast
    assert 'python-version: ["3.11", "3.12"]' in full
    assert "scripts/ci_full.sh --backend" in full
    assert "scripts/ci_fast.sh --backend" in (ROOT / "scripts/ci_full.sh").read_text(
        encoding="utf-8"
    )
    assert "verify_migrations_postgres.sh" in full
    assert "timeout-minutes: 30" in full
    for gate in ("pip-audit", "gitleaks", "sbom", "trivy"):
        assert gate in security.lower()


def test_runtime_verification_uses_declared_or_container_python() -> None:
    kernel_verify = (ROOT / "scripts/verify_kernel_loop.sh").read_text(encoding="utf-8")
    docker_verify = (ROOT / "scripts/verify_all_docker.sh").read_text(encoding="utf-8")

    assert 'PYTHON_BIN="${PYTHON_BIN:-python}"' in kernel_verify
    assert '"$PYTHON_BIN" -m unittest tests.test_kernel_agent_loop -v' in kernel_verify
    assert "python3 -m unittest tests.test_kernel_agent_loop" not in kernel_verify
    assert "docker compose --profile test build test-runner" in docker_verify
    assert "TEST_RUNNER=(" in docker_verify
    assert "test-runner" in (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert (ROOT / "deploy/docker/Dockerfile.test").exists()
    assert '--volume "$PROJECT_DIR:/workspace:ro"' in docker_verify
    assert '"${TEST_RUNNER[@]}" python -m unittest tests.test_kernel_agent_loop -v' in docker_verify
