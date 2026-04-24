import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendEpistemicBadgeContractTests(unittest.TestCase):
    def test_chat_message_contains_epistemic_badge(self):
        txt = (ROOT / "frontend/src/components/ChatMessage.tsx").read_text(encoding="utf-8")
        self.assertIn("parseEpistemicMeta", txt)
        self.assertIn("levelBadge", txt)
        self.assertIn("FACT", txt)
        self.assertIn("SPECULATION", txt)


if __name__ == "__main__":
    unittest.main()
