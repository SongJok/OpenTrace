"""
Memory Evolution System — Case → Pattern → Skill abstraction pipeline.
Includes: MemoryCompressor, MemoryEvolution, MemoryReinforcement.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from infra.cache.redis_client import get_memory_redis
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.json_parser import parse_llm_json
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)

PATTERN_KEY = "opentrace:memory:patterns"
SKILL_KEY = "opentrace:memory:skills"


@dataclass
class MemoryPattern:
    pattern_id: str
    description: str
    strategy: str
    source_cases: list[str] = field(default_factory=list)
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)


@dataclass
class MemorySkill:
    skill_id: str
    name: str
    description: str
    trigger_conditions: list[str] = field(default_factory=list)
    action_template: str = ""
    weight: float = 1.0
    use_count: int = 0
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Memory Compressor
# ---------------------------------------------------------------------------
_COMPRESS_SYS = (
    "Compress the following memories into a concise summary preserving key facts. "
    "Return ONLY the compressed text."
)
_CLUSTER_SYS = (
    "Group these memories into thematic clusters. "
    'Return JSON: {"clusters": [{"theme": str, "summary": str, "ids": [int]}]}'
)


class MemoryCompressor:
    def __init__(self) -> None:
        self._gw = get_model_gateway()

    async def compress(self, memories: list[str], max_tokens: int = 512) -> str:
        if not memories:
            return ""
        text = "\n".join(f"- {m[:300]}" for m in memories[:30])
        resp = await self._gw.complete(
            messages=[
                LLMMessage(role="system", content=_COMPRESS_SYS),
                LLMMessage(role="user", content=text),
            ],
            role=LLMRole.COMPRESS, temperature=0.1, max_tokens=max_tokens,
        )
        return resp.content

    async def cluster(self, memories: list[str]) -> list[dict[str, Any]]:
        if len(memories) < 3:
            return [{"theme": "general", "summary": memories[0] if memories else "",
                     "ids": list(range(len(memories)))}]
        text = "\n".join(f"{i}: {m[:200]}" for i, m in enumerate(memories[:40]))
        resp = await self._gw.complete(
            messages=[
                LLMMessage(role="system", content=_CLUSTER_SYS),
                LLMMessage(role="user", content=text),
            ],
            role=LLMRole.COMPRESS, temperature=0.0, max_tokens=512,
        )
        try:
            parsed = parse_llm_json(resp.content)
            if parsed and isinstance(parsed, dict):
                return parsed.get("clusters", [])
        except Exception:  # noqa: BLE001
            pass
        return [{"theme": "general", "summary": "", "ids": list(range(len(memories)))}]


# ---------------------------------------------------------------------------
# Memory Evolution  (Case → Pattern → Skill)
# ---------------------------------------------------------------------------
_EVOLVE_SYS = """\
You are a cognitive abstraction engine.
Given interaction cases, extract a reusable pattern and skill.
Return JSON ONLY:
{"pattern": "...", "strategy": "...", "skill_name": "...",
 "skill_description": "...", "trigger_conditions": ["..."]}
"""


class MemoryEvolution:
    """
    Periodically abstracts accumulated cases into patterns and skills.
    Patterns capture WHAT is common; skills capture HOW to handle it.
    """

    def __init__(self) -> None:
        self._gw = get_model_gateway()

    async def evolve(
        self, cases: list[dict[str, Any]], min_cases: int = 3
    ) -> tuple[Optional[MemoryPattern], Optional[MemorySkill]]:
        if len(cases) < min_cases:
            return None, None

        with tracer.start_as_current_span("memory.evolve") as span:
            span.set_attribute("cases.count", len(cases))
            case_text = "\n".join(
                f"Case {i+1}: Q={c.get('query','')[:150]} "
                f"| score={c.get('score', 0):.2f}"
                for i, c in enumerate(cases[:20])
            )
            resp = await self._gw.complete(
                messages=[
                    LLMMessage(role="system", content=_EVOLVE_SYS),
                    LLMMessage(role="user", content=case_text),
                ],
                role=LLMRole.COMPRESS, temperature=0.2, max_tokens=512,
            )
            pattern, skill = self._parse(resp.content, cases)
            if pattern:
                await self._save_pattern(pattern)
            if skill:
                await self._save_skill(skill)
            return pattern, skill

    def _parse(
        self, text: str, cases: list[dict[str, Any]]
    ) -> tuple[Optional[MemoryPattern], Optional[MemorySkill]]:
        parsed = parse_llm_json(text)
        if not parsed or not isinstance(parsed, dict):
            return None, None
        try:
            d = parsed
            pid = str(uuid.uuid4())[:8]
            pattern = MemoryPattern(
                pattern_id=pid,
                description=d.get("pattern", ""),
                strategy=d.get("strategy", ""),
                source_cases=[c.get("query", "")[:80] for c in cases[:5]],
            )
            skill = MemorySkill(
                skill_id=str(uuid.uuid4())[:8],
                name=d.get("skill_name", f"skill_{pid}"),
                description=d.get("skill_description", ""),
                trigger_conditions=d.get("trigger_conditions", []),
                action_template=d.get("strategy", ""),
            )
            return pattern, skill
        except Exception:  # noqa: BLE001
            return None, None

    async def _save_pattern(self, p: MemoryPattern) -> None:
        try:
            r = await get_memory_redis()
            await r.hset(PATTERN_KEY, p.pattern_id, json.dumps({
                "description": p.description, "strategy": p.strategy,
                "weight": p.weight, "created_at": p.created_at,
            }))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Pattern save failed", error=str(exc))

    async def _save_skill(self, s: MemorySkill) -> None:
        try:
            r = await get_memory_redis()
            await r.hset(SKILL_KEY, s.skill_id, json.dumps({
                "name": s.name, "description": s.description,
                "trigger_conditions": s.trigger_conditions,
                "action_template": s.action_template, "weight": s.weight,
            }))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skill save failed", error=str(exc))

    async def load_all(self) -> tuple[list[MemoryPattern], list[MemorySkill]]:
        patterns: list[MemoryPattern] = []
        skills: list[MemorySkill] = []
        try:
            r = await get_memory_redis()
            for pid, raw in (await r.hgetall(PATTERN_KEY)).items():
                d = json.loads(raw)
                patterns.append(MemoryPattern(
                    pattern_id=pid, description=d.get("description", ""),
                    strategy=d.get("strategy", ""), weight=d.get("weight", 1.0),
                ))
            for sid, raw in (await r.hgetall(SKILL_KEY)).items():
                d = json.loads(raw)
                skills.append(MemorySkill(
                    skill_id=sid, name=d.get("name", ""),
                    description=d.get("description", ""),
                    trigger_conditions=d.get("trigger_conditions", []),
                    action_template=d.get("action_template", ""),
                    weight=d.get("weight", 1.0),
                ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("load_all failed", error=str(exc))
        return patterns, skills


# ---------------------------------------------------------------------------
# Memory Reinforcement
# ---------------------------------------------------------------------------
REINFORCE_KEY = "opentrace:memory:weights"


class MemoryReinforcement:
    """
    Strengthens memories on success, weakens on failure.
    Persists weights to Redis so they survive restarts.
    Memories with weight <= 0 are candidates for forgetting.
    """

    _STRENGTHEN = 1.0
    _WEAKEN = 0.5
    _MAX_WEIGHT = 10.0
    _MIN_WEIGHT = 0.0

    async def reinforce(
        self, memory_id: str, success: bool, delta: Optional[float] = None
    ) -> float:
        weight = await self._get_weight(memory_id)
        if success:
            weight = min(self._MAX_WEIGHT, weight + (delta or self._STRENGTHEN))
        else:
            weight = max(self._MIN_WEIGHT, weight - (delta or self._WEAKEN))
        await self._set_weight(memory_id, weight)
        logger.debug("Memory reinforced", memory_id=memory_id,
                     success=success, weight=round(weight, 2))
        return weight

    async def get_weight(self, memory_id: str) -> float:
        return await self._get_weight(memory_id)

    async def prune_weak(
        self, threshold: float = 0.1
    ) -> list[str]:
        """Return IDs of memories below threshold (caller decides to delete)."""
        pruned: list[str] = []
        try:
            r = await get_memory_redis()
            all_weights = await r.hgetall(REINFORCE_KEY)
            for mid, w_str in all_weights.items():
                if float(w_str) <= threshold:
                    pruned.append(mid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("prune_weak failed", error=str(exc))
        return pruned

    async def _get_weight(self, memory_id: str) -> float:
        try:
            r = await get_memory_redis()
            v = await r.hget(REINFORCE_KEY, memory_id)
            return float(v) if v else 1.0
        except Exception:  # noqa: BLE001
            return 1.0

    async def _set_weight(self, memory_id: str, weight: float) -> None:
        try:
            r = await get_memory_redis()
            await r.hset(REINFORCE_KEY, memory_id, str(weight))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Weight set failed", error=str(exc))
