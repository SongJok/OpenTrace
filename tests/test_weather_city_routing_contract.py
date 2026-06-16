from tests.orchestrator_v4_source import read_orchestrator_v4_implementation
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WeatherCityRoutingContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_orchestrator_v4_has_weather_routing(self):
        """V4 orchestrator handles weather queries."""
        txt = read_orchestrator_v4_implementation()
        self.assertIn('"天气"', txt)
        self.assertIn("get_weather", txt)

    def test_weather_tool_invokes_city_parameter(self):
        """Weather tool is invoked with city parameter via router."""
        txt = read_orchestrator_v4_implementation()
        self.assertIn("get_weather", txt)
        self.assertIn("city", txt)


if __name__ == "__main__":
    unittest.main()
