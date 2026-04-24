import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendToolCardsContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_chat_message_has_tool_card_parser(self):
        txt = self._read("frontend/src/components/ChatMessage.tsx")
        self.assertIn("function tryParseToolCard", txt)
        self.assertIn("toolCard?.type === 'time'", txt)
        self.assertIn("toolCard?.type === 'weather'", txt)

    def test_time_weather_card_labels_exist(self):
        txt = self._read("frontend/src/components/ChatMessage.tsx")
        self.assertIn("🕒 当前时间", txt)
        self.assertIn("🌤️", txt)
        self.assertIn("温度：", txt)
        self.assertIn("湿度：", txt)


if __name__ == "__main__":
    unittest.main()
