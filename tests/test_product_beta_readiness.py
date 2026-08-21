"""产品整体受控 Beta 的单一真相与发布门禁合同。"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_product_manifest_and_public_docs_declare_controlled_beta() -> None:
    manifest = yaml.safe_load(
        (ROOT / "docs/architecture/runtime_manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["product"]["maturity"] == "Beta"
    assert manifest["enterprise_knowledge"]["maturity"] == "Beta"
    assert manifest["compatibility_runtime"]["maturity"] == "Alpha"

    for relative_path in (
        "README.md",
        "README-EN.md",
        "docs/PROJECT_SUMMARY.md",
        "docs/architecture_overview.md",
        "docs/CAPABILITY_MATURITY.md",
    ):
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "Beta" in content


def test_product_beta_gate_requires_real_results_for_release() -> None:
    gate = (ROOT / "scripts/run_product_beta_gate.sh").read_text(encoding="utf-8")
    for command in (
        "check_public_release.py",
        "check_architecture_manifest.py",
        "check_migration_policy.py",
        "check_enterprise_boundaries.py",
        "python -m pytest -q",
        "check_import_boundaries.sh",
        "python -m alembic heads",
        "npm test",
        "npm run build",
    ):
        assert command in gate
    assert "ENTERPRISE_EVAL_RESULTS_DIR" in gate
    assert "ENTERPRISE_CAPACITY_REPORT" in gate
    assert "--verify-report" in gate
    assert "--release-subject" in gate
    assert "git status --porcelain" in gate
    assert "--require-results" in gate
    assert "--validate-contracts" in gate
    assert "_fixture_executor" not in gate

    generator = (ROOT / "scripts/generate_feature_flag_docs.py").read_text(encoding="utf-8")
    assert "受控企业 Beta" in generator


def test_schema_sync_budget_is_documented_and_not_a_feature_flag() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    config_truth = (ROOT / "docs/CONFIG_TRUTH.md").read_text(encoding="utf-8")
    flag_registry = (ROOT / "docs/FEATURE_FLAG_REGISTRY.md").read_text(encoding="utf-8")
    for name in (
        "DATABASE_SCHEMA_SYNC_PAGE_SIZE",
        "DATABASE_SCHEMA_SYNC_MAX_TABLES",
        "DATABASE_SCHEMA_SYNC_MAX_COLUMNS",
    ):
        assert name in env_example
        assert name in config_truth
        assert name in flag_registry
    assert "非 Feature Flag" in flag_registry
