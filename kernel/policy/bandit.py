"""
Bandit Policy — ε-greedy + UCB1 multi-armed bandit for online strategy selection.
Persists arm statistics to Redis so learning survives restarts.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from infra.cache.redis_client import get_memory_redis
from infra.observability.logger import get_logger

logger = get_logger(__name__)

BANDIT_KEY = "opentrace:bandit:arms"
BANDIT_TTL = 90 * 24 * 3600  # 90 days

# All cognitive routing actions
ACTIONS = [
    "FAST",
    "REASON_COT",
    "REASON_TOT",
    "RAG",
    "TOOL",
    "MULTI_AGENT",
]


@dataclass
class ArmStats:
    action: str
    count: int = 0
    total_reward: float = 0.0
    mean_reward: float = 0.0
    last_updated: float = field(default_factory=time.time)

    def update(self, reward: float) -> None:
        self.count += 1
        # Incremental mean: Qn = Qn-1 + (r - Qn-1) / n
        self.mean_reward += (reward - self.mean_reward) / self.count
        self.total_reward += reward
        self.last_updated = time.time()

    def ucb1(self, total_pulls: int, c: float = 1.414) -> float:
        """Upper Confidence Bound — balances exploitation vs exploration."""
        if self.count == 0:
            return float("inf")
        return self.mean_reward + c * math.sqrt(math.log(total_pulls + 1) / self.count)


class BanditPolicy:
    """
    Multi-Armed Bandit with two selection modes:
      - epsilon_greedy: simple exploration/exploitation
      - ucb1: principled exploration with confidence bounds (default)

    Arm statistics are persisted to Redis for cross-restart learning.
    """

    def __init__(
        self,
        actions: list[str] | None = None,
        epsilon: float = 0.1,
        mode: str = "ucb1",  # "epsilon_greedy" | "ucb1"
    ) -> None:
        self.actions = actions or ACTIONS
        self.epsilon = epsilon
        self.mode = mode
        self._arms: dict[str, ArmStats] = {a: ArmStats(action=a) for a in self.actions}
        self._total_pulls: int = 0

    def select(self, available_actions: list[str] | None = None) -> str:
        """Select the best action. Exploration vs exploitation based on mode."""
        actions = available_actions or self.actions
        if not actions:
            return self.actions[0]

        if self.mode == "ucb1":
            return self._ucb1_select(actions)
        return self._epsilon_greedy_select(actions)

    def _epsilon_greedy_select(self, actions: list[str]) -> str:
        if random.random() < self.epsilon:
            return random.choice(actions)
        return max(actions, key=lambda a: self._arms[a].mean_reward if a in self._arms else 0.0)

    def _ucb1_select(self, actions: list[str]) -> str:
        return max(
            actions,
            key=lambda a: (
                self._arms[a].ucb1(self._total_pulls) if a in self._arms else float("inf")
            ),
        )

    def update(self, action: str, reward: float) -> None:
        """Record the reward for an action and update its statistics."""
        if action not in self._arms:
            self._arms[action] = ArmStats(action=action)
        self._arms[action].update(reward)
        self._total_pulls += 1
        logger.debug(
            "Bandit update",
            action=action,
            reward=round(reward, 3),
            mean=round(self._arms[action].mean_reward, 3),
            count=self._arms[action].count,
        )

    def get_stats(self) -> dict[str, dict[str, Any]]:
        return {
            a: {
                "count": s.count,
                "mean_reward": round(s.mean_reward, 4),
                "total_reward": round(s.total_reward, 4),
            }
            for a, s in self._arms.items()
        }

    async def save(self) -> None:
        """Persist arm statistics to Redis."""
        try:
            r = await get_memory_redis()
            payload = json.dumps(
                {
                    "arms": {
                        a: {
                            "count": s.count,
                            "total_reward": s.total_reward,
                            "mean_reward": s.mean_reward,
                            "last_updated": s.last_updated,
                        }
                        for a, s in self._arms.items()
                    },
                    "total_pulls": self._total_pulls,
                    "saved_at": time.time(),
                }
            )
            await r.setex(BANDIT_KEY, BANDIT_TTL, payload)
            logger.debug("Bandit stats saved", total_pulls=self._total_pulls)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bandit save failed", error=str(exc))

    async def load(self) -> None:
        """Load persisted arm statistics from Redis."""
        try:
            r = await get_memory_redis()
            raw = await r.get(BANDIT_KEY)
            if not raw:
                return
            data = json.loads(raw)
            self._total_pulls = data.get("total_pulls", 0)
            for action, stats in data.get("arms", {}).items():
                if action in self._arms:
                    self._arms[action].count = stats.get("count", 0)
                    self._arms[action].total_reward = stats.get("total_reward", 0.0)
                    self._arms[action].mean_reward = stats.get("mean_reward", 0.0)
            logger.info("Bandit stats loaded", total_pulls=self._total_pulls)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bandit load failed", error=str(exc))
