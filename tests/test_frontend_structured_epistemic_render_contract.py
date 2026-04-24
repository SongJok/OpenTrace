import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendStructuredEpistemicRenderContractTests(unittest.TestCase):
    def test_chat_input_passes_annotations_to_store(self):
        txt = (ROOT / "frontend/src/components/ChatInput.tsx").read_text(encoding="utf-8")
        self.assertIn("setLastAssistantAnnotations", txt)
        self.assertIn("onFinalAnswer: async (content, executionGraph, citations, annotations)", txt)

    def test_chat_message_reads_structured_annotations(self):
        txt = (ROOT / "frontend/src/components/ChatMessage.tsx").read_text(encoding="utf-8")
        self.assertIn("annotations?.[0]?.annotation?.level", txt)
        self.assertIn("annotations?.[0]?.annotation?.confidence", txt)
        self.assertIn("annotations?.[0]?.annotation?.caveats", txt)


if __name__ == "__main__":
    unittest.main()
