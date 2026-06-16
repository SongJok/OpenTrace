from tests.orchestrator_v4_source import read_orchestrator_v4_implementation
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ToolAgentNormalizationContractTests(unittest.TestCase):
    def test_tool_agent_has_normalization_metadata(self):
        txt = read_orchestrator_v4_implementation()
        self.assertIn("metadata", txt)
        self.assertIn("normalized", txt)
        self.assertIn("tool_name", txt)
        self.assertIn("payload", txt)

    def test_tool_agent_supports_time_weather_tool_types(self):
        txt = read_orchestrator_v4_implementation()
        self.assertIn('"type": "time"', txt)
        self.assertIn('"type": "weather"', txt)
        self.assertIn('"type": "tool"', txt)


if __name__ == "__main__":
    unittest.main()
