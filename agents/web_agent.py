from __future__ import annotations

import json
import re

from agents.base import AgentResult, BaseAgent, TaskMessage
from execution.tool_router.router import ToolRouter


class WebAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("web")

    def _normalize(self, raw: str) -> tuple[str, dict]:
        s = (raw or "").strip()
        if not s:
            return ("未获取到联网结果", {"source": "web_search", "items": []})
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                # common shapes: {items:[...]} or {results:[...]}
                items = obj.get("items") or obj.get("results") or []
                if isinstance(items, list) and items:
                    lines = []
                    norm_items = []
                    for i, it in enumerate(items[:5], start=1):
                        if isinstance(it, dict):
                            title = str(it.get("title") or it.get("name") or f"结果{i}")
                            snippet = str(it.get("snippet") or it.get("summary") or "")
                            url = str(it.get("url") or "")
                            lines.append(f"{i}. {title} {('- ' + snippet) if snippet else ''}".strip())
                            norm_items.append({"title": title, "snippet": snippet, "url": url})
                        else:
                            lines.append(f"{i}. {str(it)}")
                            norm_items.append({"title": str(it), "snippet": "", "url": ""})
                    return ("\n".join(lines), {"source": "web_search", "items": norm_items})
                return ("未检索到相关新闻结果。", {"source": "web_search", "items": []})
            if isinstance(obj, list):
                lines = [f"{i+1}. {str(x)}" for i, x in enumerate(obj[:5])]
                return ("\n".join(lines), {"source": "web_search", "items": [{"title": str(x)} for x in obj[:5]]})
        except Exception:
            pass
        return (s[:1200], {"source": "web_search", "items": []})

    async def execute(self, task: TaskMessage) -> AgentResult:
        try:
            router = ToolRouter()
            url_match = re.search(r"https?://[^\s<>'\"]+", task.query or "", re.IGNORECASE)
            if url_match:
                out = await router.execute_by_name(
                    name="web_fetch",
                    url=url_match.group(0).rstrip(".,，。!?！？"),
                    session_id=task.session_id or "",
                )
            else:
                out = await router.execute_by_name(
                    name="web_search",
                    query=task.query,
                    session_id=task.session_id or "",
                )
            raw = str(out or "").strip()
            low = raw.lower()
            if (
                (not raw)
                or low.startswith("web search unavailable")
                or low.startswith("web search error")
                or low.startswith("web fetch unavailable")
                or low.startswith("web fetch error")
                or low.startswith("tool error")
            ):
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    confidence=0.0,
                    metadata={"source": "web_search", "items": []},
                    error=raw or "web_search returned empty",
                )

            content, metadata = self._normalize(raw)
            items = metadata.get("items", [])
            evidence = [
                self._make_evidence(
                    source=f"web:{item.get('url', '')}",
                    source_type="web_search",
                    payload={"title": item.get("title", ""), "snippet": item.get("snippet", ""), "url": item.get("url", "")},
                    credibility=0.6,
                    relevance=0.7,
                )
                for item in items
            ]
            from kernel.result_reference import ResultRef, serialize_refs

            result_refs = [
                ResultRef(
                    ref_id=f"web:{item.get('url', task.task_id)}",
                    type="web_source",
                    title=f"Web: {item.get('title', 'No title')}",
                    summary=(item.get('snippet', '') or '')[:120],
                    payload={"url": item.get("url", ""), "title": item.get("title", ""), "snippet": item.get("snippet", "")},
                    source_agent="web",
                    message_id=task.task_id,
                )
                for item in items[:5]
            ]
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=content,
                confidence=0.72,
                metadata={**metadata, "result_refs": serialize_refs(result_refs)},
                evidence=evidence,
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(task_id=task.task_id, agent_type=self.agent_type, status="error", content="", error=str(exc))
