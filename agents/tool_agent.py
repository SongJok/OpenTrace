from __future__ import annotations

import ast
import json
import re

from agents.base import AgentResult, BaseAgent, TaskMessage
from execution.tool_router.router import ToolRouter

_MATH_EXPR = re.compile(r"[\d]+\s*[\+\-\*\/\^]\s*[\d]")

def _looks_like_math(text: str) -> bool:
    return bool(_MATH_EXPR.search((text or "").strip()))


class ToolAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("tool")

    def _format_weather_content(self, payload: dict) -> str:
        city = str(payload.get("location") or payload.get("city") or "天气").strip()
        current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
        forecast = payload.get("forecast") if isinstance(payload.get("forecast"), list) else []

        temp = current.get("temperature") if isinstance(current, dict) else payload.get("temperature")
        condition = current.get("condition") if isinstance(current, dict) else payload.get("condition")
        humidity = current.get("humidity") if isinstance(current, dict) else payload.get("humidity")
        wind_speed = current.get("wind_speed") if isinstance(current, dict) else payload.get("wind_speed")
        wind_direction = current.get("wind_direction") if isinstance(current, dict) else payload.get("wind_direction")

        parts = []
        headline = city
        if temp is not None or condition:
            temp_text = f"{temp}℃" if temp is not None else "未知温度"
            cond_text = str(condition or "天气情况未知")
            headline = f"{city}当前{cond_text}，气温约{temp_text}"
        parts.append(headline)

        if humidity is not None or wind_speed is not None or wind_direction:
            detail_bits = []
            if humidity is not None:
                detail_bits.append(f"湿度约{humidity}%")
            if wind_speed is not None:
                detail_bits.append(f"风速约{wind_speed}m/s")
            if wind_direction:
                detail_bits.append(f"风向{wind_direction}")
            parts.append("，".join(detail_bits))

        if forecast:
            forecast_lines = []
            for item in forecast[:3]:
                if not isinstance(item, dict):
                    continue
                date = str(item.get("date") or "").strip()
                high = item.get("high")
                low = item.get("low")
                cond = str(item.get("condition") or "").strip()
                if date or cond or high is not None or low is not None:
                    span = ""
                    if high is not None and low is not None:
                        span = f"{low}℃~{high}℃"
                    elif high is not None:
                        span = f"最高{high}℃"
                    elif low is not None:
                        span = f"最低{low}℃"
                    segment = "，".join([x for x in [date, cond, span] if x])
                    forecast_lines.append(f"- {segment}")
            if forecast_lines:
                parts.append("未来几天参考：\n" + "\n".join(forecast_lines))

        return "\n".join(parts)

    def _parse_payload(self, raw: str) -> tuple[str, dict]:
        parsed = None
        try:
            parsed = json.loads(raw)
        except Exception:
            try:
                parsed = ast.literal_eval(raw)
            except Exception:
                parsed = None

        if isinstance(parsed, dict):
            if "time" in parsed and "timestamp" in parsed:
                return "datetime", {"type": "time", **parsed}
            if "city" in parsed and ("temperature" in parsed or "weather" in parsed):
                return "weather", {"type": "weather", **parsed}
            return "tool", {"type": "tool", "text": raw, "raw": parsed}

        return "tool", {"type": "tool", "text": raw}

    async def execute(self, task: TaskMessage) -> AgentResult:
        try:
            router = ToolRouter()
            out = await router.execute(intent=task.query, query=task.query, session_id=task.session_id or "")
            tool_name = "tool"
            if not out:
                q = (task.query or "").lower()
                if any(k in q for k in ["几点", "时间", "time", "日期", "date"]):
                    tool_name = "datetime"
                    out = await router.execute_by_name(name="datetime", query=task.query, session_id=task.session_id or "")
                elif any(k in q for k in ["天气", "weather", "温度", "下雨"]):
                    tool_name = "get_weather"
                    out = await router.execute_by_name(name="get_weather", query=task.query, session_id=task.session_id or "")
                elif _looks_like_math(q):
                    tool_name = "calculator"
                    out = await router.execute_by_name(name="calculator", expression=q, session_id=task.session_id or "")

            raw = str(out or "").strip()
            low = raw.lower()
            if (not raw) or low.startswith("error:") or low.startswith("tool error") or low.startswith("weather error") or low.startswith("web search error") or low.startswith("web search unavailable"):
                return AgentResult(task_id=task.task_id, agent_type="tool", status="error", content="", confidence=0.0, error=raw or "no tool matched")

            parsed_tool_name, payload = self._parse_payload(raw)
            if parsed_tool_name != "tool":
                tool_name = parsed_tool_name

            text_preview = payload.get("text") if isinstance(payload, dict) else None
            if tool_name == "weather" and isinstance(payload, dict):
                text_preview = self._format_weather_content(payload)
            elif tool_name in ("datetime", "get_current_time") and isinstance(payload, dict):
                time_str = payload.get("time") or payload.get("datetime") or ""
                tz_str = payload.get("timezone") or ""
                text_preview = f"当前时间：{time_str}" + (f"（{tz_str}）" if tz_str else "")
            elif not text_preview and isinstance(payload, dict):
                text_preview = json.dumps(payload, ensure_ascii=False)

            body = str(text_preview or out)[:1200]
            return AgentResult(
                task_id=task.task_id,
                agent_type="tool",
                status="success",
                content=body,
                confidence=0.88,
                metadata={
                    "normalized": True,
                    "tool_name": tool_name,
                    "payload": payload,
                },
                evidence=[
                    self._make_evidence(
                        source=f"tool:{tool_name}",
                        source_type="tool",
                        payload=payload,
                        credibility=0.85,
                        relevance=0.9,
                    )
                ],
                evidence_objects=[
                    self._make_evidence_object(
                        content=body,
                        source_type="tool",
                        credibility=0.85,
                        relevance=0.9,
                        tool_name=tool_name,
                    )
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(task_id=task.task_id, agent_type="tool", status="error", content="", error=str(exc))
