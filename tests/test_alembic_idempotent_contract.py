import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_DIR = ROOT / "alembic" / "versions"


class AlembicIdempotentContractTests(unittest.TestCase):
    def test_key_migrations_use_schema_inspection(self):
        targets = [
            "20260405_reasoning_artifacts.py",
            "20260406_chat_session_stage1.py",
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


if __name__ == "__main__":
    unittest.main()
