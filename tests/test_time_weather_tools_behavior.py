import json
import os
import unittest

from tools.builtin_tools.builtins import tool_get_current_time, tool_get_weather


class TimeWeatherToolsBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_current_time_returns_required_fields(self):
        raw = await tool_get_current_time(timezone="local")
        data = json.loads(raw)
        self.assertIn("time", data)
        self.assertIn("timestamp", data)
        self.assertIn("timezone", data)

    async def test_get_weather_without_api_key_returns_explicit_error(self):
        old_stack = os.environ.pop("WEATHER_STACK_API_KEY", None)
        old_owm = os.environ.pop("WEATHER_API_KEY", None)
        try:
            raw = await tool_get_weather(city="北京")
            self.assertIn("Weather error: no weather API key configured", raw)
        finally:
            if old_stack is not None:
                os.environ["WEATHER_STACK_API_KEY"] = old_stack
            if old_owm is not None:
                os.environ["WEATHER_API_KEY"] = old_owm

    async def test_get_weather_requires_city(self):
        raw = await tool_get_weather(city="")
        self.assertIn("Weather error: city is required", raw)


if __name__ == "__main__":
    unittest.main()
