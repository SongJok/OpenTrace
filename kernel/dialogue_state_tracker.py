"""对话状态跟踪 — 短追问与上一轮 plan/result 的确定性展开。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DialogueState:
    active_domain: str = ""
    referenced_previous_result: bool = False
    referenced_agent_type: str = ""
    resolved_query: str = ""
    turn_type: str = "neutral"
    metadata: dict[str, Any] = field(default_factory=dict)


_FOLLOW_UP_RE = re.compile(
    r"^(那|那么|还有|另外|具体|详细|按|根据|再|继续)",
)
_SHORT_Q_RE = re.compile(r"^[\u4e00-\u9fff\w\s]{1,18}[？?]?$")


class DialogueStateTracker:

    def _last_agent_from_results(self, previous_results: Any) -> str:
        if not isinstance(previous_results, list):
            return ""
        for item in reversed(previous_results):
            if isinstance(item, dict):
                agent = str(item.get("source_agent") or item.get("agent_type") or "")
                if agent:
                    return agent
        return ""

    def _expand_from_plan(self, query: str, previous_plan: Any) -> str:
        if not isinstance(previous_plan, dict):
            return query
        goal = str(previous_plan.get("user_goal") or previous_plan.get("query") or "").strip()
        if goal and goal not in query:
            return f"{goal}；{query}"
        return query

    async def track(
        self,
        query: str,
        previous_plan: Any = None,
        previous_results: Any = None,
        history: Any = None,
    ) -> DialogueState:
        q = (query or "").strip()
        if not q:
            return DialogueState(resolved_query=q)

        # Only expand when the user explicitly continues the prior turn (not every short sentence).
        is_follow = bool(_FOLLOW_UP_RE.match(q))
        resolved = q
        if is_follow:
            resolved = self._expand_from_plan(q, previous_plan)

        agent = self._last_agent_from_results(previous_results)
        domain = ""
        if isinstance(previous_plan, dict):
            domain = str(previous_plan.get("domain") or previous_plan.get("task_type") or "")

        referenced = is_follow and bool(previous_results or previous_plan)
        turn_type = "follow_up" if is_follow else "neutral"

        return DialogueState(
            active_domain=domain,
            referenced_previous_result=referenced,
            referenced_agent_type=agent,
            resolved_query=resolved,
            turn_type=turn_type,
            metadata={"history_len": len(history) if isinstance(history, list) else 0},
        )