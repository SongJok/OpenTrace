import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_DIR = ROOT / "alembic" / "versions"


class AlembicIdempotentContractTests(unittest.TestCase):
    def test_key_migrations_use_schema_inspection(self):
        targets = [
            "20260405_reasoning_artifacts.py",
            "20260406_chat_session_stage1.py",
            "20260606_enterprise_tenant_tables.py",
            "20260606_enterprise_tenants_rls.py",
            "20260610_merge_cognitive_enterprise_heads.py",
            "20260611_billing_invoice_tables.py",
            "20260613_documents_tenant_workspace.py",
        ]
        for name in targets:
            p = ALEMBIC_DIR / name
            self.assertTrue(p.exists(), f"missing migration: {name}")
            code = p.read_text(encoding="utf-8")
            self.assertIn("sa.inspect", code)
            self.assertTrue(
                ("get_columns" in code) or ("get_indexes" in code),
                f"{name} should check existing columns/indexes before altering",
            )

    def test_runtime_schema_guard_covers_chat_session_columns(self):
        p = ROOT / "infra" / "storage" / "database.py"
        code = p.read_text(encoding="utf-8")
        self.assertIn("ensure_runtime_schema", code)
        for column in [
            "display_title",
            "turn_count",
            "last_decision_type",
            "tags",
            "pinned",
            "archived_at",
            "tenant_id",
            "org_id",
            "workspace_id",
            "active_response_id",
            "branch_root_response_id",
        ]:
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", code)

    def test_api_startup_runs_runtime_schema_guard(self):
        p = ROOT / "gateway" / "api_gateway" / "main.py"
        code = p.read_text(encoding="utf-8")
        self.assertIn("ensure_runtime_schema", code)
        self.assertIn("await ensure_runtime_schema()", code)

    def test_managed_env_schema_guard_is_readonly(self):
        p = ROOT / "infra" / "storage" / "database.py"
        code = p.read_text(encoding="utf-8")
        self.assertIn('settings.app_env in {"staging", "production"}', code)
        self.assertIn("await _verify_runtime_schema(conn)", code)
        self.assertIn("Runtime schema readiness failed", code)

    def test_empty_revision_reconciler_is_data_preserving_and_dependency_aware(self):
        code = (ROOT / "scripts" / "reconcile_pre_migration_schema.py").read_text(encoding="utf-8")
        self.assertIn("_reconcile_empty_revision", code)
        self.assertIn("_runtime_model_tables", code)
        self.assertIn("_foreign_key_dependencies", code)
        self.assertIn("pg_catalog.pg_constraint", code)
        self.assertIn("EMPTY_REVISION_UNSAFE_TABLES", code)
        self.assertIn("EMPTY_REVISION_ALWAYS_PRESERVE_TABLES", code)
        self.assertIn("DROP TABLE", code)
        self.assertIn("拒绝自动清理", code)

    def test_real_postgres_verifies_empty_revision_data_preservation(self):
        code = (ROOT / "scripts" / "verify_migrations_postgres.sh").read_text(encoding="utf-8")
        self.assertIn("MIGRATION_EMPTY_REVISION_TEST_DATABASE_URL", code)
        self.assertIn("scripts/reconcile_pre_migration_schema.py", code)
        self.assertIn("migration-company-version", code)
        self.assertIn("印章借用必须审批并留痕", code)


if __name__ == "__main__":
    unittest.main()
