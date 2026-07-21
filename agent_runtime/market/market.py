"""
Agent Market — competitive multi-agent selection with bidding + reputation.

Mechanism:
  Task → agents bid → top-K selected → parallel execute → fuse → update reputation
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

from infra.cache.redis_client import get_memory_redis
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)

REPUTATION_KEY = "opentrace:market:reputation"
AGENT_REGISTRY_KEY = "opentrace:market:agents"


@dataclass
class AgentSpec:
    """
    Describes a registered agent's capabilities.
    fn: async callable (query: str, context: str) -> str
    """
    agent_id: str
    name: str
    skills: list[str]              # keyword capabilities
    fn: Callable[[str, str], Awaitable[str]]
    reputation: float = 1.0        # starts neutral
    latency_avg: float = 1.0       # rolling avg latency
    success_rate: float = 1.0      # rolling success rate
    speciality: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)

    def bid(self, task: str) -> float:
        """
        Compute bid score for a task.
        = skill_match_count * reputation / latency_avg
        """
        task_lower = task.lower()
        matches = sum(1 for s in self.skills if s.lower() in task_lower)
        if matches == 0:
            return 0.0
        return (matches * self.reputation) / max(self.latency_avg, 0.1)


class ReputationSystem:
    """
    Tracks per-agent reputation scores in Redis.
    success → score * 1.1 (capped at 5.0)
    failure → score * 0.9 (floored at 0.1)
    """

    _BOOST = 1.1
    _PENALTY = 0.9
    _MAX = 5.0
    _MIN = 0.1

    async def update(
        self,
        agent: AgentSpec,
        success: bool,
        latency: float = 1.0,
    ) -> None:
        agent.reputation = max(
            self._MIN,
            min(self._MAX, agent.reputation * (self._BOOST if success else self._PENALTY)),
        )
        # Rolling latency average (EMA α=0.3)
        agent.latency_avg = 0.7 * agent.latency_avg + 0.3 * latency
        # Rolling success rate (EMA α=0.2)
        agent.success_rate = 0.8 * agent.success_rate + 0.2 * (1.0 if success else 0.0)
        await self._persist(agent)
        logger.debug(
            "Reputation updated",
            agent=agent.name,
            success=success,
            rep=round(agent.reputation, 3),
        )

    async def load(self, agent: AgentSpec) -> None:
        """Load persisted reputation for an agent."""
        try:
            r = await get_memory_redis()
            raw = await r.hget(REPUTATION_KEY, agent.agent_id)
            if raw:
                d = json.loads(raw)
                agent.reputation = d.get("reputation", 1.0)
                agent.latency_avg = d.get("latency_avg", 1.0)
                agent.success_rate = d.get("success_rate", 1.0)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Reputation load failed", error=str(exc))

    async def _persist(self, agent: AgentSpec) -> None:
        try:
            r = await get_memory_redis()
            await r.hset(
                REPUTATION_KEY,
                agent.agent_id,
                json.dumps({
                    "reputation": agent.reputation,
                    "latency_avg": agent.latency_avg,
                    "success_rate": agent.success_rate,
                    "updated_at": time.time(),
                }),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Reputation persist failed", error=str(exc))


class AgentMarket:
    """
    Competitive agent market.

    Usage::
        market = AgentMarket()
        market.register(AgentSpec(...))
        result = await market.execute(task="...", context="...", top_k=3)
    """

    def __init__(self, top_k: int = 3) -> None:
        self._agents: dict[str, AgentSpec] = {}
        self._reputation = ReputationSystem()
        self._top_k = top_k

    def register(self, spec: AgentSpec) -> None:
        self._agents[spec.agent_id] = spec
        logger.info("Agent registered", name=spec.name, skills=spec.skills)

    def deregister(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    def select_agents(
        self, task: str, top_k: Optional[int] = None
    ) -> list[tuple[AgentSpec, float]]:
        """Run bidding and return (agent, bid) pairs sorted descending."""
        bids = [
            (agent, agent.bid(task))
            for agent in self._agents.values()
        ]
        bids = [(a, b) for a, b in bids if b > 0]
        bids.sort(key=lambda x: x[1], reverse=True)
        k = top_k or self._top_k
        return bids[:k]

    async def execute(
        self,
        task: str,
        context: str = "",
        top_k: Optional[int] = None,
        fusion: str = "best",   # "best" | "vote" | "concat"
    ) -> str:
        """
        Select top-K agents, run in parallel, fuse results.
        fusion modes:
          best   — return highest-bid agent's answer
          vote   — majority vote (for classification tasks)
          concat — concatenate all answers (for synthesis tasks)
        """
        with tracer.start_as_current_span("agent_market.execute") as span:
            selected = self.select_agents(task, top_k)
            if not selected:
                return "No agents available for this task."

            span.set_attribute("market.agents_selected", len(selected))

            async def _run_one(
                agent: AgentSpec, bid: float
            ) -> tuple[AgentSpec, float, str, float]:
                t0 = time.monotonic()
                success = True
                try:
                    answer = await asyncio.wait_for(agent.fn(task, context), timeout=60.0)
                except Exception as exc:  # noqa: BLE001
                    answer = f"[{agent.name} failed: {exc}]"
                    success = False
                latency = time.monotonic() - t0
                await self._reputation.update(agent, success, latency)
                return agent, bid, answer, latency

            outcomes = await asyncio.gather(
                *[_run_one(a, b) for a, b in selected],
                return_exceptions=False,
            )

            return self._fuse(outcomes, fusion, task)

    def _fuse(
        self,
        outcomes: list[tuple[AgentSpec, float, str, float]],
        mode: str,
        task: str,
    ) -> str:
        # Filter failed outcomes
        valid = [(a, b, ans, lat) for a, b, ans, lat in outcomes if not ans.startswith("[")]
        if not valid:
            valid = outcomes  # fallback: include failures

        if mode == "best" or len(valid) == 1:
            # Highest bid wins
            best = max(valid, key=lambda x: x[1])
            return best[2]

        if mode == "vote":
            from collections import Counter
            counts = Counter(ans for _, _, ans, _ in valid)
            return counts.most_common(1)[0][0]

        # concat: combine all unique answers
        seen: set[str] = set()
        parts: list[str] = []
        for agent, _, ans, _ in valid:
            if ans not in seen:
                parts.append(f"[{agent.name}]: {ans}")
                seen.add(ans)
        return "\n\n".join(parts)

    def list_agents(self) -> list[dict[str, Any]]:
        return [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "skills": a.skills,
                "reputation": round(a.reputation, 3),
                "success_rate": round(a.success_rate, 3),
                "latency_avg": round(a.latency_avg, 3),
            }
            for a in self._agents.values()
        ]


# Module-level singleton
agent_market = AgentMarket()
