import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage6SyncAnnotationsContractTests(unittest.TestCase):
    def test_chat_response_has_execution_graph_and_annotations(self):
        txt = (ROOT / "gateway/api_gateway/routers/chat.py").read_text(encoding="utf-8")
        self.assertIn("execution_graph: dict[str, Any] | None = None", txt)
        self.assertIn('result.metadata.get("annotations"', txt)
        self.assertIn('result.metadata.get("execution_graph"', txt)

    def test_chat_input_sync_fallback_writes_annotations(self):
        txt = (ROOT / "frontend/src/components/ChatInput.tsx").read_text(encoding="utf-8")
        self.assertIn("if (Array.isArray(sync.annotations) && sync.annotations.length)", txt)
        self.assertIn("setLastAssistantAnnotations", txt)
        self.assertIn("if (sync.execution_graph)", txt)


if __name__ == "__main__":
    unittest.main()
