"""
RL Policy Engine — Rule + Bandit + LLM hybrid with reward feedback loop.

Reward formula: R = α·correctness + β·user_feedback - γ·latency - δ·cost
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.policy.bandit import ACTIONS, BanditPolicy
from kernel.policy.engine import Decision, Route, Strategy

logger = get_logger(__name__)
tracer = get_tracer(__name__)

_ALPHA = 1.0  # correctness
_BETA = 0.5  # user feedback
_GAMMA = 0.1  # latency penalty
_DELTA = 0.05  # cost penalty

_ACTION_MAP: dict[str, tuple[Route, Strategy]] = {
    "FAST": (Route.FAST, Strategy.DIRECT),
    "REASON_COT": (Route.REASON, Strategy.COT),
    "REASON_TOT": (Route.REASON, Strategy.TOT),
    "RAG": (Route.TOOL, Strategy.RAG),
    "TOOL": (Route.TOOL, Strategy.SEARCH),
    "MULTI_AGENT": (Route.MULTI_AGENT, Strategy.COT),
}


@dataclass
class PolicyState:
    intent_complexity: float = 0.5
    has_history: bool = False
    requires_tools: bool = False
    requires_knowledge: bool = False
    multi_step: bool = False
    category: str = "qa"
    uncertainty: float = 0.5
    language: str = "en"

    @classmethod
    def from_intent(cls, intent: Any, context: Any = None) -> PolicyState:
        complexity = getattr(intent, "complexity", 0.5)
        uncertainty = 1.0 - abs(complexity - 0.5) * 2
        return cls(
            intent_complexity=complexity,
            has_history=bool(context),
            requires_tools=getattr(intent, "requires_tools", False),
            requires_knowledge=getattr(intent, "requires_knowledge", False),
            multi_step=getattr(intent, "multi_step", False),
            category=getattr(intent, "category", "qa"),
            uncertainty=uncertainty,
            language=getattr(intent, "language", "en"),
        )

    def to_feature_vector(self) -> list[float]:
        return [
            self.intent_complexity,
            float(self.has_history),
            float(self.requires_tools),
            float(self.requires_knowledge),
            float(self.multi_step),
            self.uncertainty,
        ]


def compute_reward(
    correctness: float = 0.8,
    latency: float = 1.0,
    cost: float = 0.01,
    user_feedback: float = 0.0,
) -> float:
    r = (
        _ALPHA * correctness
        + _BETA * user_feedback
        - _GAMMA * min(latency, 10.0)
        - _DELTA * min(cost, 1.0)
    )
    return max(-1.0, min(1.0, r))


class RLPolicyEngine:
    """
    Online RL-augmented policy engine.
      Stage 1: rule-based until bandit has MIN_PULLS data points
      Stage 2: UCB1 bandit selects optimal cognitive action
      Stage 3: update(result) closes the reward feedback loop
    """

    _MIN_PULLS = 10

    def __init__(
        self,
        bandit: BanditPolicy | None = None,
        rule_engine: Any | None = None,
    ) -> None:
        self.bandit = bandit or BanditPolicy(mode="ucb1")
        self._rule_engine = rule_engine
        self._runtime_strategy: dict[str, Any] = {}

    def _get_rule_engine(self):
        if self._rule_engine is None:
            from kernel.policy.engine import PolicyEngine

            self._rule_engine = PolicyEngine(use_llm_fallback=False)
        return self._rule_engine

    def update_strategy(self, strategy: dict[str, Any]) -> None:
        self._runtime_strategy.update(strategy)
        if self._rule_engine:
            self._rule_engine.update_strategy(strategy)

    async def decide(self, intent: Any, context: Any = None) -> Decision:
        with tracer.start_as_current_span("rl_policy.decide") as span:
            # Bootstrap with rule engine
            if self.bandit._total_pulls < self._MIN_PULLS:
                engine = self._get_rule_engine()
                decision = await engine.decide(intent, context)
                span.set_attribute("rl.source", "rules")
                return decision

            state = PolicyState.from_intent(intent, context)
            candidates = self._candidate_actions(state)
            action = self.bandit.select(candidates)
            route, strategy = _ACTION_MAP.get(action, (Route.REASON, Strategy.COT))

            arm = self.bandit._arms.get(action)
            confidence = arm.mean_reward if arm else 0.5
            count = arm.count if arm else 0

            span.set_attribute("rl.source", "bandit")
            span.set_attribute("rl.action", action)
            span.set_attribute("rl.pulls", self.bandit._total_pulls)

            logger.debug("RL decision", action=action, confidence=round(confidence, 3), n=count)
            return Decision(
                route=route,
                strategy=strategy,
                confidence=confidence,
                rationale=f"bandit:{action} n={count}",
            )

    def _candidate_actions(self, state: PolicyState) -> list[str]:
        """Filter actions by state context to reduce exploration space."""
        if state.requires_tools:
            return ["TOOL", "RAG", "MULTI_AGENT", "REASON_COT"]
        if state.multi_step and state.intent_complexity > 0.6:
            return ["MULTI_AGENT", "REASON_TOT", "REASON_COT"]
        if state.intent_complexity < 0.25:
            return ["FAST", "REASON_COT"]
        return ACTIONS

    async def update(
        self,
        action: str,
        correctness: float = 0.8,
        latency: float = 1.0,
        cost: float = 0.01,
        user_feedback: float = 0.0,
    ) -> float:
        """Compute reward and update bandit. Call after each execution."""
        reward = compute_reward(
            correctness=correctness,
            latency=latency,
            cost=cost,
            user_feedback=user_feedback,
        )
        self.bandit.update(action, reward)
        # Async save every 20 pulls
        if self.bandit._total_pulls % 20 == 0:
            import asyncio

            asyncio.create_task(self.bandit.save())
        return reward

    async def load(self) -> None:
        """Load persisted bandit stats on startup."""
        await self.bandit.load()


# Module-level singleton
rl_policy_engine = RLPolicyEngine()
