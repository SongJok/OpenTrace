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


if __name__ == "__main__":
    unittest.main()
