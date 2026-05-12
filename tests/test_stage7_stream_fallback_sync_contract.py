import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage7StreamFallbackSyncContractTests(unittest.TestCase):
    def test_chat_input_sync_fallback_sets_structured_fields(self):
        txt = (ROOT / "frontend/src/components/ChatInput.tsx").read_text(encoding="utf-8")
        self.assertIn("apiChatSync(token, currentSessionId, query, {", txt)
        self.assertIn("dataSourceContext", txt)
        self.assertIn("force_database: needDataSource", txt)
        self.assertIn("enabled_skills", txt)
        self.assertIn("disabled_skills", txt)
        self.assertIn("tool_permission_token", txt)
        self.assertIn("sync.execution_graph", txt)
        self.assertIn("sync.annotations", txt)
        self.assertIn("setLastAssistantAnnotations", txt)

    def test_chat_response_schema_has_sync_structured_fields(self):
        txt = (ROOT / "gateway/api_gateway/routers/chat.py").read_text(encoding="utf-8")
        self.assertIn("annotations: list[dict[str, Any]]", txt)
        self.assertIn("execution_graph: dict[str, Any] | None", txt)
        self.assertIn("_database_intent", txt)
        self.assertIn("force_database", txt)
        self.assertIn("data_source_context", txt)
        self.assertIn("tool_permission_token", txt)


if __name__ == "__main__":
    unittest.main()
