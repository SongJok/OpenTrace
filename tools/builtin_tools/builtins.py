"""
Built-in tools: datetime, calculator, web_search, python_repl, summarize.
"""
from __future__ import annotations

import datetime
import math
import os
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


@registry.tool(
    name="get_weather",
    description="Get current weather by city using OpenWeatherMap.",
    tags=["weather", "temperature", "humidity", "天气", "气温", "温度"],
)
async def tool_get_weather(city: str = "", **_) -> str:
    import httpx

    api_key = (os.getenv("WEATHER_API_KEY") or "").strip()
    if not city.strip():
        return "Weather error: city is required"
    if not api_key:
        return "Weather error: WEATHER_API_KEY not configured"

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=10.0) as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": api_key, "units": "metric", "lang": "zh_cn"},
            )
            resp.raise_for_status()
            data = resp.json()
        weather = (data.get("weather") or [{}])[0]
        main = data.get("main") or {}
        return (
            "{"
            f"\"city\": \"{city}\", "
            f"\"temperature\": {main.get('temp', 'null')}, "
            f"\"weather\": \"{weather.get('description', '')}\", "
            f"\"humidity\": {main.get('humidity', 'null')}"
            "}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Weather error: {exc}"


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
