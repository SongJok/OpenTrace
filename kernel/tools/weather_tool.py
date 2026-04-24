from __future__ import annotations

import os

import httpx

from .base import BaseTool


class WeatherTool(BaseTool):
    name = "get_weather"
    description = "Get current weather by city"

    def run(self, city: str, **kwargs) -> dict[str, object]:
        api_key = (os.getenv("WEATHER_API_KEY") or "").strip()
        if not api_key:
            return {"error": "WEATHER_API_KEY not configured", "city": city}

        try:
            resp = httpx.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": api_key, "units": "metric", "lang": "zh_cn"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "city": city,
                "temperature": data.get("main", {}).get("temp"),
                "weather": (data.get("weather") or [{}])[0].get("description", ""),
                "humidity": data.get("main", {}).get("humidity"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "city": city}
