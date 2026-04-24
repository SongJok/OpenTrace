import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LLMWikiRagContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_model_and_migration_define_document_llmwiki(self):
        model_code = self._read("infra/storage/models.py")
        migration_code = self._read("alembic/versions/20260422_add_document_llmwiki.py")
        self.assertIn("class DocumentLLMWiki(Base)", model_code)
        self.assertIn('__tablename__ = "document_llmwiki"', model_code)
        self.assertIn('op.create_table(', migration_code)
        self.assertIn('"document_llmwiki"', migration_code)

    def test_document_plugin_has_generation_and_retrieval_paths(self):
        plugin_code = self._read("plugins/document_plugin.py")
        self.assertIn("async def generate_llmwiki_entries", plugin_code)
        self.assertIn("async def search_llmwiki", plugin_code)
        self.assertIn("DocumentLLMWiki.keywords.overlap", plugin_code)

    def test_settings_and_env_expose_llmwiki_switches(self):
        settings_code = self._read("infra/config/settings.py")
        env_code = self._read(".env.example")
        self.assertIn("llmwiki_enabled", settings_code)
        self.assertIn("llmwiki_model", settings_code)
        self.assertIn("llmwiki_top_k", settings_code)
        self.assertIn("LLMWIKI_ENABLED=true", env_code)
        self.assertIn("LLMWIKI_MODEL=qwen3.5-27b", env_code)


if __name__ == "__main__":
    unittest.main()
