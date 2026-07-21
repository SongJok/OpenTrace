"""
Self-Play — Autonomous self-training system.
Pipeline: TaskGenerator → Solver → Critic → learn(RL + Memory + Flywheel)
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)

_DOMAINS = [
    "mathematics", "science", "history", "coding", "logic",
    "general_knowledge", "creative_writing", "data_analysis",
]


@dataclass
class SelfPlayEpisode:
    episode_id: str
    task: str
    answer: str
    critique: dict[str, Any]
    reward: float
    action: str = "REASON_COT"
    latency: float = 0.0
    domain: str = ""


# ---------------------------------------------------------------------------
# Task Generator
# ---------------------------------------------------------------------------
_TASK_GEN_SYS = (
    "Generate a challenging answerable question for AI training. "
    "Return JSON ONLY: {\"task\": \"...\", \"domain\": \"...\", "
    "\"difficulty\": 0.0-1.0, \"expected_route\": \"FAST|REASON_COT|REASON_TOT|TOOL\"}"
)


class TaskGenerator:
    def __init__(self) -> None:
        self._gw = get_model_gateway()
        self._idx = 0

    async def generate(
        self, domain: Optional[str] = None, difficulty: float = 0.6
    ) -> dict[str, Any]:
        d = domain or _DOMAINS[self._idx % len(_DOMAINS)]
        self._idx += 1
        resp = await self._gw.complete(
            messages=[
                LLMMessage(role="system", content=_TASK_GEN_SYS),
                LLMMessage(role="user", content=f"Domain: {d}\nDifficulty: {difficulty:.1f}"),
            ],
            role=LLMRole.PLANNING, temperature=0.8, max_tokens=256,
        )
        m = re.search(r"\{.*\}", resp.content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                pass
        return {"task": resp.content.strip()[:300], "domain": d,
                "difficulty": difficulty, "expected_route": "REASON_COT"}


# ---------------------------------------------------------------------------
# Self-Play Engine
# ---------------------------------------------------------------------------
_CRITIC_SYS = (
    "Evaluate this AI answer rigorously. "
    "Return JSON ONLY: {\"score\": 0.0-1.0, \"correct\": true|false, "
    "\"feedback\": \"...\", \"action\": \"FAST|REASON_COT|REASON_TOT|TOOL\"}"
)


class SelfPlay:
    """
    Autonomous self-training loop.
    Each episode: generate → solve → critique → learn.
    """

    def __init__(self, task_generator: Optional[TaskGenerator] = None) -> None:
        self._gen = task_generator or TaskGenerator()
        self._gw = get_model_gateway()

    async def run_episode(
        self, domain: Optional[str] = None, difficulty: float = 0.6
    ) -> SelfPlayEpisode:
        eid = str(uuid.uuid4())[:8]
        task_info = await self._gen.generate(domain=domain, difficulty=difficulty)
        task = task_info.get("task", "")
        expected = task_info.get("expected_route", "REASON_COT")
        domain_name = task_info.get("domain", domain or "general")

        t0 = time.monotonic()
        answer = await self._solve(task)
        latency = time.monotonic() - t0

        critique = await self._critique(task, answer)
        score = float(critique.get("score", 0.5))
        action = critique.get("action", expected)

        return SelfPlayEpisode(
            episode_id=eid, task=task, answer=answer,
            critique=critique, reward=score, action=action,
            latency=latency, domain=domain_name,
        )

    async def run_batch(
        self, n: int = 5, domain: Optional[str] = None,
        difficulty: float = 0.6, concurrency: int = 3,
    ) -> list[SelfPlayEpisode]:
        sem = asyncio.Semaphore(concurrency)

        async def _one(_: int) -> SelfPlayEpisode:
            async with sem:
                return await self.run_episode(domain=domain, difficulty=difficulty)

        return await asyncio.gather(*[_one(i) for i in range(n)])

    async def learn(
        self, episodes: list[SelfPlayEpisode]
    ) -> dict[str, Any]:
        """
        Feed episode results back into:
          1. RLPolicyEngine — bandit arm reward
          2. DataFlywheel  — for next LearningEngine cycle
          3. MemoryEvolution store (via EvolutionMemoryRouter)
        """
        total_reward = 0.0
        rl_updates = 0
        mem_stores = 0

        for ep in episodes:
            total_reward += ep.reward
            # 1. RL bandit update
            try:
                from kernel.policy.rl_engine import rl_policy_engine
                await rl_policy_engine.update(
                    action=ep.action,
                    correctness=ep.reward,
                    latency=ep.latency,
                )
                rl_updates += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("RL update failed", error=str(exc))

            # 2. Flywheel
            try:
                from evolution.data_flywheel.flywheel import flywheel
                # Simulate feedback event
                flywheel._examples.append({
                    "query": ep.task,
                    "response": ep.answer,
                    "score": ep.reward,
                    "route": ep.action,
                    "type": "self_play",
                    "latency": ep.latency,
                })
                mem_stores += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("Flywheel update failed", error=str(exc))

        avg_reward = total_reward / len(episodes) if episodes else 0.0
        logger.info(
            "SelfPlay.learn complete",
            episodes=len(episodes),
            avg_reward=round(avg_reward, 3),
            rl_updates=rl_updates,
        )
        return {
            "episodes": len(episodes),
            "avg_reward": avg_reward,
            "rl_updates": rl_updates,
            "mem_stores": mem_stores,
        }

    async def _solve(self, task: str) -> str:
        resp = await self._gw.complete(
            messages=[LLMMessage(role="user", content=task)],
            role=LLMRole.QUERY, temperature=0.3, max_tokens=512,
        )
        return resp.content

    async def _critique(self, task: str, answer: str) -> dict[str, Any]:
        resp = await self._gw.complete(
            messages=[
                LLMMessage(role="system", content=_CRITIC_SYS),
                LLMMessage(role="user", content=f"Q: {task}\nA: {answer[:1000]}"),
            ],
            role=LLMRole.COMPRESS, temperature=0.0, max_tokens=256,
        )
        m = re.search(r"\{.*\}", resp.content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                pass
        return {"score": 0.5, "correct": False, "feedback": resp.content[:200],
                "action": "REASON_COT"}


# Module-level singleton
self_play = SelfPlay()
