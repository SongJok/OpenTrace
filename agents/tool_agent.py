from __future__ import annotations

import ast
import json

from agents.base import AgentResult, BaseAgent, TaskMessage
from execution.tool_router.router import ToolRouter


class ToolAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("tool")

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

            raw = str(out or "").strip()
            low = raw.lower()
            if (not raw) or low.startswith("error:") or low.startswith("tool error") or low.startswith("weather error") or low.startswith("web search error") or low.startswith("web search unavailable"):
                return AgentResult(task_id=task.task_id, agent_type="tool", status="error", content="", confidence=0.0, error=raw or "no tool matched")

            parsed_tool_name, payload = self._parse_payload(raw)
            if parsed_tool_name != "tool":
                tool_name = parsed_tool_name

            text_preview = payload.get("text") if isinstance(payload, dict) else None
            if not text_preview and isinstance(payload, dict):
                text_preview = json.dumps(payload, ensure_ascii=False)

            return AgentResult(
                task_id=task.task_id,
                agent_type="tool",
                status="success",
                content=str(text_preview or out)[:1200],
                confidence=0.88,
                metadata={
                    "normalized": True,
                    "tool_name": tool_name,
                    "payload": payload,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(task_id=task.task_id, agent_type="tool", status="error", content="", error=str(exc))
