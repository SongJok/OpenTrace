import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage7StreamFallbackSyncContractTests(unittest.TestCase):
    def test_chat_input_uses_one_canonical_responses_stream(self):
        txt = (ROOT / "frontend/src/components/ChatInput.tsx").read_text(encoding="utf-8")
        self.assertIn("await apiChatStream(", txt)
        self.assertIn("executionProfile", txt)
        self.assertIn("assistant_profile_id", txt)
        self.assertNotIn("project_id", txt)
        self.assertNotIn("data_source_ids", txt)
        self.assertIn("setLastAssistantAnnotations", txt)
        self.assertNotIn("apiChatSync", txt)

    def test_responses_schema_has_opentrace_extension(self):
        txt = (ROOT / "gateway/api_gateway/routers/responses.py").read_text(encoding="utf-8")
        self.assertIn("class OpenTraceOptions", txt)
        self.assertIn("enabled_skills", txt)
        self.assertIn("data_source_ids", txt)
        self.assertIn("assistant_profile_id", txt)


if __name__ == "__main__":
    unittest.main()
