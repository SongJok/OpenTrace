"""Skills Agent — executes installed skills matching the user query."""
from __future__ import annotations

import asyncio
import json
from agents.base import BaseAgent, AgentResult, TaskMessage
from skills.store.marketplace import marketplace

# Map force_mode to preferred skill_type for prioritized matching
_FORCE_MODE_SKILL_TYPE = {
    "anomaly_tracking": "anomaly",
    "data_query": "data_query",
    "data_analysis": "text_analysis",
}

_SKILL_TIMEOUT_SEC = 10.0


class SkillsAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(agent_type="skills")

    async def execute(self, task: TaskMessage) -> AgentResult:
        skills = marketplace.list_installed()
        if not skills:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="当前没有已安装的技能。请在 Skills 页面创建或安装技能后重试。",
                confidence=0.5,
                metadata={"installed_count": 0},
            )

        # Filter by enabled_skills whitelist if provided
        enabled_ids: list[str] | None = (task.params or {}).get("enabled_skills")
        if enabled_ids:
            skills = [s for s in skills if s.skill_id in enabled_ids]
            if not skills:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="success",
                    content=f"白名单技能 {enabled_ids} 均未安装。",
                    confidence=0.3,
                    metadata={"installed_count": 0, "enabled_requested": enabled_ids},
                )

        force_mode: str | None = (task.params or {}).get("force_mode")
        test_input = {"query": task.query, "session_id": task.session_id or "", "params": task.params or {}}
        results = []
        best_result = None
        best_score = 0.0

        for skill in skills:
            try:
                outcome = await asyncio.wait_for(
                    asyncio.to_thread(marketplace.test_skill, skill.skill_id, test_input),
                    timeout=_SKILL_TIMEOUT_SEC,
                )
                if outcome.get("success"):
                    score = _score_match(skill, task.query, force_mode)
                    results.append({"skill_id": skill.skill_id, "name": skill.name, "score": score, "output": outcome.get("output")})
                    if score > best_score:
                        best_score = score
                        best_result = outcome.get("output")
                else:
                    results.append({"skill_id": skill.skill_id, "name": skill.name, "error": outcome.get("error", "unknown")})
            except asyncio.TimeoutError:
                results.append({"skill_id": skill.skill_id, "name": skill.name, "error": "timeout"})
            except Exception as exc:
                results.append({"skill_id": skill.skill_id, "name": skill.name, "error": str(exc)})

        if best_result is not None:
            content = json.dumps(best_result, ensure_ascii=False) if isinstance(best_result, dict) else str(best_result)
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=content,
                confidence=max(0.7, best_score),
                metadata={"matched_skills": len(results), "all_results": results},
            )

        preview = ", ".join(s.name for s in skills[:5])
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=f"已尝试 {len(skills)} 个已安装技能（{preview}），但未找到完全匹配的结果。",
            confidence=0.4,
            metadata={"all_results": results},
        )


def _score_match(skill, query: str, force_mode: str | None = None) -> float:
    """Heuristic score: skill name/type/description overlap with query, plus force_mode alignment."""
    q = query.lower()
    score = 0.0
    name = (skill.name or "").lower()
    desc = (skill.description or "").lower()
    stype = (skill.skill_type or "").lower()

    if name and name in q:
        score += 0.5
    if force_mode:
        preferred = _FORCE_MODE_SKILL_TYPE.get(force_mode, "")
        if preferred and preferred in stype:
            score += 0.4
    if desc and any(word in q for word in desc.split() if len(word) > 1):
        score += 0.15
    if stype and stype in q:
        score += 0.15
    score += 0.1
    return min(score, 1.0)
