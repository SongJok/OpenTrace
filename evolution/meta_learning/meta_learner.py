"""
Meta-Learning — Strategy Self-Evolution System.

Pipeline: Analyze → Mutate (LLM) → A/B Evaluate → Select → Deploy

Old policy → LLM mutation → new policy variant → real-traffic evaluation
→ survival-of-the-fittest selection → deploy winner.
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
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)

META_POLICY_KEY = "opentrace:meta:policies"
META_ACTIVE_KEY = "opentrace:meta:active_policy"
TOP_K_POLICIES = 3


# ---------------------------------------------------------------------------
# Policy representation
# ---------------------------------------------------------------------------
@dataclass
class MetaPolicy:
    policy_id: str
    name: str
    rules: dict[str, Any]          # structured strategy rules
    score: float = 0.0
    eval_count: int = 0
    generation: int = 0            # mutation generation
    parent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    is_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "rules": self.rules,
            "score": self.score,
            "eval_count": self.eval_count,
            "generation": self.generation,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MetaPolicy":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# Default seed policy
_SEED_POLICY = MetaPolicy(
    policy_id="seed",
    name="seed_policy_v1",
    rules={
        "reasoning_depth": "standard",
        "tool_preference": "balanced",
        "memory_weight": 0.5,
        "exploration_rate": 0.1,
        "retry_on_low_score": True,
        "min_confidence": 0.6,
    },
    score=0.5,
    is_active=True,
)


# ---------------------------------------------------------------------------
# Policy Mutator — LLM-driven strategy mutation
# ---------------------------------------------------------------------------
_MUTATE_SYSTEM = """\
You are a meta-learning optimizer for an AI cognitive system.
Given the current strategy policy and its performance metrics,
propose an improved variant that addresses the weaknesses.

Return JSON ONLY:
{
  "name": "policy_name_v{generation}",
  "rules": {
    "reasoning_depth": "standard|deep|adaptive",
    "tool_preference": "aggressive|balanced|conservative",
    "memory_weight": 0.0-1.0,
    "exploration_rate": 0.0-0.3,
    "retry_on_low_score": true|false,
    "min_confidence": 0.3-0.9
  },
  "rationale": "explanation of changes"
}
"""


class PolicyMutator:
    def __init__(self) -> None:
        self._gw = get_model_gateway()

    async def mutate(
        self,
        policy: MetaPolicy,
        performance_history: list[dict[str, Any]],
    ) -> MetaPolicy:
        """
        Generate a mutated policy using LLM analysis of performance data.
        """
        perf_summary = self._summarize_performance(performance_history)
        prompt = (
            f"Current policy: {json.dumps(policy.rules, indent=2)}\n"
            f"Performance: {perf_summary}\n"
            f"Generation: {policy.generation + 1}\n"
            "Generate an improved policy."
        )
        resp = await self._gw.complete(
            messages=[
                LLMMessage(role="system", content=_MUTATE_SYSTEM),
                LLMMessage(role="user", content=prompt),
            ],
            role=LLMRole.PLANNING,
            temperature=0.4,
            max_tokens=512,
        )
        return self._parse(resp.content, policy)

    def _parse(self, text: str, parent: MetaPolicy) -> MetaPolicy:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                d = json.loads(m.group(0))
                return MetaPolicy(
                    policy_id=str(uuid.uuid4())[:8],
                    name=d.get("name", f"{parent.name}_mut"),
                    rules=d.get("rules", dict(parent.rules)),
                    generation=parent.generation + 1,
                    parent_id=parent.policy_id,
                )
            except Exception:  # noqa: BLE001
                pass
        # Fallback: minor random perturbation
        import copy, random
        new_rules = copy.deepcopy(parent.rules)
        new_rules["exploration_rate"] = round(
            min(0.3, max(0.0, new_rules.get("exploration_rate", 0.1)
                         + random.uniform(-0.05, 0.05))), 3
        )
        return MetaPolicy(
            policy_id=str(uuid.uuid4())[:8],
            name=f"{parent.name}_mut{parent.generation+1}",
            rules=new_rules,
            generation=parent.generation + 1,
            parent_id=parent.policy_id,
        )

    def _summarize_performance(
        self, history: list[dict[str, Any]]
    ) -> str:
        if not history:
            return "No performance data yet."
        avg_score = sum(h.get("score", 0) for h in history) / len(history)
        avg_latency = sum(h.get("latency", 0) for h in history) / len(history)
        return (
            f"avg_score={avg_score:.3f}, avg_latency={avg_latency:.2f}s, "
            f"n={len(history)}"
        )


# ---------------------------------------------------------------------------
# Policy Evaluator
# ---------------------------------------------------------------------------
class PolicyEvaluator:
    """
    Evaluates a policy against real-traffic execution results.
    Score = weighted average of correctness - latency_penalty - cost_penalty.
    """

    def evaluate(
        self,
        policy: MetaPolicy,
        results: list[dict[str, Any]],
    ) -> float:
        if not results:
            return policy.score
        total = sum(
            1.0 * r.get("correctness", r.get("score", 0.5))
            - 0.1 * min(r.get("latency", 1.0), 10.0)
            - 0.05 * min(r.get("cost", 0.01), 1.0)
            for r in results
        )
        reward = total / len(results)
        # Incremental mean update
        n = policy.eval_count + len(results)
        policy.score = (
            (policy.score * policy.eval_count + reward * len(results)) / n
        )
        policy.eval_count = n
        return policy.score


# ---------------------------------------------------------------------------
# Policy Selector — survival-of-the-fittest
# ---------------------------------------------------------------------------
class PolicySelector:
    def __init__(self, top_k: int = TOP_K_POLICIES) -> None:
        self.top_k = top_k

    def select(self, policies: list[MetaPolicy]) -> list[MetaPolicy]:
        """Sort by score, return top-K. Mark best as active."""
        ranked = sorted(policies, key=lambda p: p.score, reverse=True)
        survivors = ranked[: self.top_k]
        for p in survivors:
            p.is_active = False
        if survivors:
            survivors[0].is_active = True
        return survivors


# ---------------------------------------------------------------------------
# MetaLearner — orchestrates the full evolution cycle
# ---------------------------------------------------------------------------
class MetaLearner:
    """
    Full meta-learning evolution loop:
      1. Load current policies from Redis
      2. Collect performance data from LearningEngine
      3. Evaluate all policies
      4. Mutate the best policy to generate a new candidate
      5. Select survivors (top-K)
      6. Persist winning policies + deploy active policy
    """

    def __init__(
        self,
        mutator: Optional[PolicyMutator] = None,
        evaluator: Optional[PolicyEvaluator] = None,
        selector: Optional[PolicySelector] = None,
    ) -> None:
        self.mutator = mutator or PolicyMutator()
        self.evaluator = evaluator or PolicyEvaluator()
        self.selector = selector or PolicySelector()
        self._policies: list[MetaPolicy] = [_SEED_POLICY]

    async def run_cycle(
        self,
        performance_data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Execute one meta-learning evolution cycle.
        Returns info about the winning policy.
        """
        with tracer.start_as_current_span("meta_learner.cycle") as span:
            # 1. Load persisted policies
            await self._load_policies()

            # 2. Evaluate all with new data
            for policy in self._policies:
                self.evaluator.evaluate(policy, performance_data)

            # 3. Mutate best policy
            best = max(self._policies, key=lambda p: p.score)
            new_policy = await self.mutator.mutate(best, performance_data)
            new_policy.score = best.score * 0.9  # slight pessimism for new policies
            self._policies.append(new_policy)

            # 4. Select survivors
            self._policies = self.selector.select(self._policies)

            # 5. Persist
            await self._save_policies()

            # 6. Deploy active policy to RL engine + orchestrator
            active = next((p for p in self._policies if p.is_active), self._policies[0])
            await self._deploy(active)

            span.set_attribute("meta.policies", len(self._policies))
            span.set_attribute("meta.active", active.name)
            span.set_attribute("meta.best_score", round(active.score, 3))

            logger.info(
                "Meta-learning cycle complete",
                active_policy=active.name,
                score=round(active.score, 3),
                generation=active.generation,
                candidates=len(self._policies),
            )
            return {
                "active_policy": active.name,
                "score": active.score,
                "generation": active.generation,
                "survivors": [p.name for p in self._policies],
            }

    async def _deploy(self, policy: MetaPolicy) -> None:
        """Push active policy rules to RL engine and policy engine at runtime."""
        try:
            from kernel.policy.rl_engine import rl_policy_engine
            rl_policy_engine.update_strategy(policy.rules)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Meta deploy to RL engine failed", error=str(exc))
        try:
            from kernel.policy.engine import PolicyEngine
            import gc
            for obj in gc.get_referrers(PolicyEngine):
                if isinstance(obj, PolicyEngine):
                    obj.update_strategy(policy.rules)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Meta deploy to PolicyEngine failed", error=str(exc))

    async def _save_policies(self) -> None:
        try:
            r = await get_memory_redis()
            payload = json.dumps([p.to_dict() for p in self._policies])
            await r.set(META_POLICY_KEY, payload)
            if self._policies:
                active = next((p for p in self._policies if p.is_active), self._policies[0])
                await r.set(META_ACTIVE_KEY, json.dumps(active.rules))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Meta policy save failed", error=str(exc))

    async def _load_policies(self) -> None:
        try:
            r = await get_memory_redis()
            raw = await r.get(META_POLICY_KEY)
            if raw:
                data = json.loads(raw)
                self._policies = [MetaPolicy.from_dict(d) for d in data]
                logger.debug("Meta policies loaded", count=len(self._policies))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Meta policy load failed", error=str(exc))

    async def get_active_rules(self) -> dict[str, Any]:
        """Return active policy rules (used by Orchestrator)."""
        try:
            r = await get_memory_redis()
            raw = await r.get(META_ACTIVE_KEY)
            if raw:
                return json.loads(raw)
        except Exception:  # noqa: BLE001
            pass
        return _SEED_POLICY.rules


# Module-level singleton
meta_learner = MetaLearner()
