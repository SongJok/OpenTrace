import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage6SyncAnnotationsContractTests(unittest.TestCase):
    def test_conversation_projection_has_summary_and_annotations(self):
        txt = (ROOT / "gateway/api_gateway/routers/conversations.py").read_text(encoding="utf-8")
        self.assertIn("execution_graph: dict | None", txt)
        self.assertIn("annotations: list[dict]", txt)

    def test_responses_stream_writes_annotations_without_legacy_sync_fallback(self):
        txt = (ROOT / "frontend/src/components/ChatInput.tsx").read_text(encoding="utf-8")
        self.assertIn("onFinalAnswer: (envelope)", txt)
        self.assertIn("setLastAssistantAnnotations", txt)
        self.assertIn("setLastAssistantTurnMeta", txt)
        self.assertNotIn("apiChatSync", txt)


if __name__ == "__main__":
    unittest.main()
