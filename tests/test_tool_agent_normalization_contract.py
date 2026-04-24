import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ToolAgentNormalizationContractTests(unittest.TestCase):
    def test_tool_agent_has_normalization_metadata(self):
        txt = (ROOT / "kernel/orchestrator_v4.py").read_text(encoding="utf-8")
        self.assertIn("metadata", txt)
        self.assertIn("normalized", txt)
        self.assertIn("tool_name", txt)
        self.assertIn("payload", txt)

    def test_tool_agent_supports_time_weather_tool_types(self):
        txt = (ROOT / "kernel/orchestrator_v4.py").read_text(encoding="utf-8")
        self.assertIn('"type": "time"', txt)
        self.assertIn('"type": "weather"', txt)
        self.assertIn('"type": "tool"', txt)


if __name__ == "__main__":
    unittest.main()
