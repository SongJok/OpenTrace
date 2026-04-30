"""
Built-in tools: datetime, calculator, web_search, python_repl, summarize.
"""
from __future__ import annotations

import datetime
import json
import math
import os

from tools.registry.registry import registry


@registry.tool(
    name="datetime",
    description="Return the current date and time in Asia/Shanghai by default.",
    tags=["time", "date", "now", "datetime", "current", "时间", "几点", "现在几点"],
)
async def tool_datetime(timezone: str = "Asia/Shanghai", **_) -> str:
    from zoneinfo import ZoneInfo

    tz = timezone or "Asia/Shanghai"
    try:
        now = datetime.datetime.now(ZoneInfo(tz))
    except Exception:
        tz = "Asia/Shanghai"
        now = datetime.datetime.now(ZoneInfo(tz))
    return (
        "{"
        f"\"time\": \"{now.strftime('%Y-%m-%d %H:%M:%S')}\", "
        f"\"timestamp\": {int(now.timestamp())}, "
        f"\"timezone\": \"{tz}\""
        "}"
    )


@registry.tool(
    name="calculator",
    description="Evaluate a safe mathematical expression and return the result.",
    tags=["calculate", "math", "compute", "arithmetic", "expression"],
)
async def tool_calculator(expression: str = "", **_) -> str:
    allowed = set("0123456789+-*/().% ")
    expr = expression.strip()
    if not expr:
        return "Error: empty expression"
    if not all(c in allowed for c in expr):
        return f"Error: unsafe characters in expression: {repr(expr)}"
    try:
        result = eval(expr, {"__builtins__": {}, "math": math}, {})  # noqa: S307
        return str(result)
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


@registry.tool(
    name="web_search",
    description="Search the web for current information using Serper API.",
    tags=["search", "web", "internet", "google", "find", "latest", "news"],
)
async def tool_web_search(query: str = "", **_) -> str:
    from infra.config.settings import settings

    api_key = (
        getattr(settings, "serper_api_key", None)
        or os.getenv("SERPER_API_KEY")
        or os.getenv("serper_api_key")
    )
    if isinstance(api_key, str):
        api_key = api_key.strip()
    if not api_key:
        return "Web search unavailable: SERPER_API_KEY not configured."

    import httpx
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 5},
            )
            resp.raise_for_status()
            data = resp.json()
        snippets = [
            f"{r.get('title', '')}: {r.get('snippet', '')}"
            for r in data.get("organic", [])[:5]
        ]
        return "\n".join(snippets) if snippets else "No results found."
    except Exception as exc:  # noqa: BLE001
        return f"Web search error: {exc}"


@registry.tool(
    name="get_current_time",
    description="Get current system time.",
    tags=["time", "datetime", "clock", "几点", "时间", "现在几点"],
)
async def tool_get_current_time(timezone: str = "Asia/Shanghai", **_) -> str:
    from zoneinfo import ZoneInfo

    tz = timezone or "Asia/Shanghai"
    try:
        now = datetime.datetime.now(ZoneInfo(tz))
    except Exception:
        now = datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
        tz = "Asia/Shanghai"
    return (
        "{"
        f"\"time\": \"{now.strftime('%Y-%m-%d %H:%M:%S')}\", "
        f"\"timestamp\": {int(now.timestamp())}, "
        f"\"timezone\": \"{tz}\""
        "}"
    )


# Mapping from Weatherstack English conditions to Chinese
_WEATHER_CONDITION_MAP: dict[str, str] = {
    "sunny": "晴",
    "clear": "晴",
    "partly cloudy": "多云",
    "cloudy": "阴",
    "overcast": "阴",
    "mist": "薄雾",
    "fog": "雾",
    "freezing fog": "冻雾",
    "patchy rain possible": "局部可能有雨",
    "patchy rain nearby": "局部有雨",
    "patchy light rain": "局部小雨",
    "light rain": "小雨",
    "moderate rain": "中雨",
    "moderate rain at times": "间歇中雨",
    "heavy rain": "大雨",
    "heavy rain at times": "间歇大雨",
    "light drizzle": "小毛毛雨",
    "patchy light drizzle": "局部毛毛雨",
    "light rain shower": "小阵雨",
    "moderate or heavy rain shower": "中到大阵雨",
    "torrential rain shower": "暴雨",
    "patchy snow possible": "局部可能有雪",
    "patchy snow nearby": "局部有雪",
    "light snow": "小雪",
    "moderate snow": "中雪",
    "heavy snow": "大雪",
    "blizzard": "暴风雪",
    "blowing snow": "吹雪",
    "light sleet": "小冰雹",
    "moderate or heavy sleet": "中到大冰雹",
    "thunderstorm": "雷暴",
    "thundery outbreaks possible": "可能有雷暴",
    "patchy light rain with thunder": "局部小雷雨",
    "moderate or heavy rain with thunder": "中到大雷雨",
}


def _map_weather_condition(raw: str) -> str:
    """Map English weather description to Chinese; fall back to original."""
    if not raw:
        return ""
    lowered = raw.strip().lower()
    # First try exact match
    if lowered in _WEATHER_CONDITION_MAP:
        return _WEATHER_CONDITION_MAP[lowered]
    # Try partial match (e.g. "Light Rain Shower" contains "light rain shower")
    for eng, zh in sorted(_WEATHER_CONDITION_MAP.items(), key=lambda x: -len(x[0])):
        if eng in lowered:
            return zh
    return raw


def _extract_city_from_query(query: str) -> str:
    import re

    _WEATHER_KEYWORDS = re.compile(
        r"(帮我查一下|查一下|帮我查|我想知道|请问|今天|明天|后天|昨天|本周|下周|这周|最近|"
        r"天气|怎么样|如何|怎样|多少度|气温|温度|下雨|下雪|刮风|雾霾|aqi|pm2\.?5|"
        r"预报|查询|会|吗|呢|啊|吧|那边|那里|这里|那儿|这儿|的)",
        re.IGNORECASE,
    )
    _parens = re.compile(r"[（(][^)）]*[)）]")
    cleaned = _WEATHER_KEYWORDS.sub("", query)
    cleaned = _parens.sub("", cleaned)
    # Remove leading/trailing punctuation and whitespace
    cleaned = re.sub(r"^[，。！？、\s]+|[，。！？、\s]+$", "", cleaned)
    city = cleaned.strip()
    city = re.sub(r"(那边|那里|这里|那儿|这儿)$", "", city).strip()
    # Remove standalone suffixes like "市", "省", "区" only if city is longer than 1 char
    if len(city) > 1:
        city = re.sub(r"(市|省|区|县|镇|村)$", "", city).strip()
    return city


def _build_weather_payload(
    city: str,
    temp: float | None = None,
    feels_like: float | None = None,
    condition: str = "",
    humidity: int | None = None,
    pressure: float | None = None,
    wind_speed: float | None = None,
    wind_direction: str | None = None,
    cloudiness: int | None = None,
    visibility: float | None = None,
    sunrise: int | str | None = None,
    sunset: int | str | None = None,
    forecast: list | None = None,
) -> dict:
    return {
        "type": "weather",
        "location": city,
        "current": {
            "temperature": temp,
            "feels_like": feels_like,
            "condition": condition,
            "humidity": humidity,
            "pressure": pressure,
            "wind_speed": wind_speed,
            "wind_direction": wind_direction,
            "cloudiness": cloudiness,
            "visibility": visibility,
            "sunrise": sunrise,
            "sunset": sunset,
        },
        "forecast": forecast or [],
        "summary": f"{city}当前{condition or '天气'}, 气温{temp if temp is not None else '-'}°C",
    }


async def _enrich_weather_payload(payload: dict) -> None:
    from model.llm_adapter.base import LLMMessage
    from model.model_gateway.gateway import LLMRole, get_model_gateway

    enrich_prompt = (
        "你是一名专业天气播报员。请基于下面的天气原始数据，生成更饱满的中文天气播报。\n"
        "要求：\n"
        "1. 只输出 JSON。\n"
        "2. 仅包含这些字段：summary, overview, feels_like_text, outfit_advice, travel_advice, risk_alert, activity_suggestion, keep_suggestion。\n"
        "3. 文风自然，适合直接给用户阅读。\n"
        "4. 不要重复原始字段名，不要编造不存在的数据。\n"
        "5. 每个字段尽量一句话。\n\n"
        f"原始数据：{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        gw = get_model_gateway()
        resp = await gw.complete(
            messages=[
                LLMMessage(role="system", content="你负责把天气结构化数据润色为中文天气播报 JSON。"),
                LLMMessage(role="user", content=enrich_prompt),
            ],
            role=LLMRole.KNOWLEDGE,
            temperature=0.4,
            max_tokens=512,
        )
        enriched = json.loads((resp.content or "").strip())
        if isinstance(enriched, dict):
            allowed = {
                "summary", "overview", "feels_like_text", "outfit_advice",
                "travel_advice", "risk_alert", "activity_suggestion", "keep_suggestion",
            }
            payload.update({k: v for k, v in enriched.items() if k in allowed})
    except Exception:
        pass


async def _fetch_weatherstack(city: str, api_key: str) -> str:
    """Fetch weather from weatherstack.com API (current + optional forecast)."""
    import httpx

    async with httpx.AsyncClient(trust_env=False, timeout=8.0) as client:
        resp = await client.get(
            "http://api.weatherstack.com/current",
            params={
                "access_key": api_key,
                "query": city,
                "units": "m",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("error"):
        return f"Weather error: weatherstack — {data['error'].get('info', 'unknown error')}"

    loc = data.get("location") or {}
    current = data.get("current") or {}

    resolved_city = loc.get("name") or city
    temp = current.get("temperature")
    feels_like = current.get("feelslike")
    condition_en = (current.get("weather_descriptions") or [""])[0]
    condition = _map_weather_condition(condition_en)
    humidity = current.get("humidity")
    pressure = current.get("pressure")
    wind_speed = current.get("wind_speed")
    wind_dir_val = current.get("wind_dir")
    wind_degree = current.get("wind_degree")
    if wind_dir_val and wind_degree is not None:
        wind_direction = f"{wind_dir_val} {wind_degree}°"
    else:
        wind_direction = wind_dir_val or (f"{wind_degree}°" if wind_degree is not None else None)
    cloudiness = current.get("cloudcover")
    visibility = current.get("visibility")

    # Astro data (sunrise / sunset as formatted strings like "05:17 AM")
    astro = current.get("astro") if isinstance(current.get("astro"), dict) else {}
    sunrise_str = astro.get("sunrise")
    sunset_str = astro.get("sunset")

    # Air quality
    aqi = current.get("air_quality") if isinstance(current.get("air_quality"), dict) else {}

    # Try forecast (separate API call; free-tier plans may reject this)
    forecast_list = []
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=6.0) as fc:
            fc_resp = await fc.get(
                "http://api.weatherstack.com/forecast",
                params={
                    "access_key": api_key,
                    "query": city,
                    "forecast_days": 3,
                    "units": "m",
                },
            )
            fc_resp.raise_for_status()
            fc_data = fc_resp.json()
            fc_forecast = (fc_data.get("forecast") or {}) if isinstance(fc_data, dict) else {}
            for day_name, day_data in (fc_forecast.items() if isinstance(fc_forecast, dict) else []):
                if not isinstance(day_data, dict):
                    continue
                forecast_list.append({
                    "date": day_data.get("date") or day_name,
                    "high": day_data.get("maxtemp"),
                    "low": day_data.get("mintemp"),
                    "condition": _map_weather_condition(
                        (day_data.get("weather_descriptions") or [""])[0]
                    ),
                })
    except Exception:
        pass  # forecast is optional on free tier

    payload = _build_weather_payload(
        city=resolved_city,
        temp=temp,
        feels_like=feels_like,
        condition=condition,
        humidity=humidity,
        pressure=pressure,
        wind_speed=wind_speed,
        wind_direction=wind_direction,
        cloudiness=cloudiness,
        visibility=visibility,
        sunrise=sunrise_str,
        sunset=sunset_str,
        forecast=forecast_list,
    )
    if aqi:
        payload["current"]["air_quality"] = {
            k: aqi.get(k) for k in ("pm2_5", "pm10", "o3", "no2", "so2", "co", "us-epa-index", "gb-defra-index")
            if aqi.get(k) is not None
        }

    await _enrich_weather_payload(payload)
    return json.dumps(payload, ensure_ascii=False)


async def _fetch_openweathermap(city: str, api_key: str) -> str:
    """Fetch weather from OpenWeatherMap API."""
    import httpx

    async with httpx.AsyncClient(trust_env=False, timeout=8.0) as client:
        resp = await client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": api_key, "units": "metric", "lang": "zh_cn"},
        )
        resp.raise_for_status()
        data = resp.json()

    weather = (data.get("weather") or [{}])[0]
    main = data.get("main") or {}
    wind = data.get("wind") or {}
    sys = data.get("sys") or {}
    clouds = data.get("clouds") or {}

    payload = _build_weather_payload(
        city=city,
        temp=main.get("temp"),
        feels_like=main.get("feels_like"),
        condition=weather.get("description", ""),
        humidity=main.get("humidity"),
        pressure=main.get("pressure"),
        wind_speed=wind.get("speed"),
        wind_direction=f"{wind.get('deg')}°" if wind.get("deg") is not None else None,
        cloudiness=clouds.get("all"),
        visibility=data.get("visibility"),
        sunrise=sys.get("sunrise"),
        sunset=sys.get("sunset"),
    )
    await _enrich_weather_payload(payload)
    return json.dumps(payload, ensure_ascii=False)


@registry.tool(
    name="get_weather",
    description="Get current weather and forecast by city using Weatherstack or OpenWeatherMap.",
    tags=["weather", "temperature", "humidity", "天气", "气温", "温度"],
)
async def tool_get_weather(city: str = "", query: str = "", **_) -> str:
    import httpx

    # ── Resolve city ──────────────────────────────────────────────
    if not city.strip() and query.strip():
        city = _extract_city_from_query(query)

    if not city.strip():
        return "Weather error: city is required (configure WEATHER_STACK_API_KEY or WEATHER_API_KEY)"

    # ── Pick provider ─────────────────────────────────────────────
    stack_key = (os.getenv("WEATHER_STACK_API_KEY") or "").strip()
    owm_key = (os.getenv("WEATHER_API_KEY") or "").strip()

    if not stack_key and not owm_key:
        return "Weather error: no weather API key configured (WEATHER_STACK_API_KEY or WEATHER_API_KEY)"

    # Try Weatherstack first, fall back to OpenWeatherMap
    if stack_key:
        try:
            return await _fetch_weatherstack(city, stack_key)
        except httpx.HTTPStatusError as exc:
            if owm_key:
                pass  # fall through to OpenWeatherMap
            else:
                return f"Weather error: Weatherstack API returned {exc.response.status_code} for city='{city}'"
        except Exception as exc:
            if owm_key:
                pass  # fall through
            else:
                return f"Weather error: {exc}"

    if owm_key:
        try:
            return await _fetch_openweathermap(city, owm_key)
        except httpx.HTTPStatusError as exc:
            return f"Weather error: OpenWeatherMap API returned {exc.response.status_code} for city='{city}'. Check your API key and city name."
        except Exception as exc:
            return f"Weather error: {exc}"

    return "Weather error: all providers failed"


@registry.tool(
    name="python_repl",
    description=(
        "Execute Python code in a sandboxed REPL and return stdout output. "
        "Use for data processing, calculations, and code testing."
    ),
    tags=["python", "code", "run", "execute", "repl", "script"],
)
async def tool_python_repl(code: str = "", **_) -> str:
    """Execute Python code safely and return stdout."""
    import asyncio
    import io
    from contextlib import redirect_stdout, redirect_stderr

    if not code.strip():
        return "Error: no code provided"

    # Block dangerous imports
    _BLOCKED = ["os.system", "subprocess", "__import__", "eval(", "exec(",
                "open(", "shutil", "pathlib", "socket", "requests", "httpx"]
    code_lower = code.lower()
    for blocked in _BLOCKED:
        if blocked in code_lower:
            return f"Error: '{blocked}' is not allowed in python_repl"

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    def _run():
        safe_globals = {
            "__builtins__": {
                "print": print, "len": len, "range": range, "enumerate": enumerate,
                "zip": zip, "map": map, "filter": filter, "sorted": sorted,
                "sum": sum, "min": min, "max": max, "abs": abs, "round": round,
                "int": int, "float": float, "str": str, "bool": bool,
                "list": list, "dict": dict, "set": set, "tuple": tuple,
                "isinstance": isinstance, "type": type, "repr": repr,
            },
            "math": math,
        }
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(code, safe_globals, {})  # noqa: S102

    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, _run), timeout=10.0
        )
        output = stdout_buf.getvalue()
        err = stderr_buf.getvalue()
        if err:
            return f"{output}\nSTDERR: {err}".strip()
        return output.strip() or "(no output)"
    except asyncio.TimeoutError:
        return "Error: code execution timed out (10s)"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


@registry.tool(
    name="summarize",
    description="Summarize a long piece of text into a concise paragraph.",
    tags=["summarize", "compress", "shorten", "tldr"],
)
async def tool_summarize(text: str = "", **_) -> str:
    if not text.strip():
        return "Error: no text provided"
    from model.llm_adapter.base import LLMMessage
    from model.model_gateway.gateway import LLMRole, get_model_gateway
    gw = get_model_gateway()
    resp = await gw.complete(
        messages=[
            LLMMessage(role="system", content="Summarize the following text concisely in 2-3 sentences."),
            LLMMessage(role="user", content=text[:4000]),
        ],
        role=LLMRole.COMPRESS,
        temperature=0.1,
        max_tokens=256,
    )
    return resp.content
