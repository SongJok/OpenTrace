import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WeatherCityRoutingContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_orchestrator_has_weather_city_alias_map(self):
        txt = self._read("kernel/orchestrator.py")
        self.assertIn('city_alias = {', txt)
        self.assertIn('"beijing": "北京"', txt)
        self.assertIn('"shanghai": "上海"', txt)
        self.assertIn('"深圳市": "深圳"', txt)
        self.assertIn('"xiamen": "厦门"', txt)

    def test_orchestrator_weather_route_uses_city_argument(self):
        txt = self._read("kernel/orchestrator.py")
        self.assertIn('calls.append({"tool": "get_weather", "query": state.query, "city": city})', txt)


if __name__ == "__main__":
    unittest.main()
