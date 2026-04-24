"""
Evolution Learning — online learning loop that applies feedback to improve
system behaviour. Stores curated examples and emits strategy updates.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from evolution.data_flywheel.flywheel import DataFlywheel
from evolution.evaluation.engine import EvaluationEngine, EvalScore
from infra.cache.redis_client import get_memory_redis
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)

LEARNING_KEY = "opentrace:learning:strategy"
EXAMPLES_KEY = "opentrace:learning:examples"
EXAMPLES_TTL = 30 * 24 * 3600


@dataclass
class LearningCycle:
    cycle_id: str
    examples_processed: int
    avg_score: float
    strategy_updates: list[str]
    timestamp: float = field(default_factory=time.time)


@dataclass
class StrategyUpdate:
    key: str
    old_value: Any
    new_value: Any
    reason: str


class LearningEngine:
    """
    Closes the self-improvement loop:
      1. Drain feedback flywheel
      2. Evaluate examples via EvaluationEngine
      3. Detect patterns + emit strategy updates
      4. Update RLPolicyEngine bandit with rewards
      5. Trigger MemoryEvolution Case→Pattern→Skill pipeline
    """

    def __init__(
        self,
        flywheel: Optional[DataFlywheel] = None,
        evaluator: Optional[EvaluationEngine] = None,
    ) -> None:
        self.flywheel = flywheel or DataFlywheel()
        self.evaluator = evaluator or EvaluationEngine()
        self._strategy: dict[str, Any] = {}
        # Lazy-loaded to avoid circular imports
        self._rl_engine = None
        self._memory_evolution = None

    def _get_rl_engine(self):
        if self._rl_engine is None:
            from kernel.policy.rl_engine import rl_policy_engine
            self._rl_engine = rl_policy_engine
        return self._rl_engine

    def _get_memory_evolution(self):
        if self._memory_evolution is None:
            from memory.evolution.evolution import MemoryEvolution
            self._memory_evolution = MemoryEvolution()
        return self._memory_evolution

    async def run_cycle(self, batch_size: int = 50) -> LearningCycle:
        import uuid
        with tracer.start_as_current_span("learning.run_cycle") as span:
            cycle_id = str(uuid.uuid4())[:8]

            # 1. Drain flywheel
            accepted = await self.flywheel.process_batch(batch_size)
            examples = self.flywheel.get_examples()

            if not examples:
                logger.info("Learning cycle: no examples to process", cycle=cycle_id)
                return LearningCycle(
                    cycle_id=cycle_id,
                    examples_processed=0,
                    avg_score=0.0,
                    strategy_updates=[],
                )

            # 2. Evaluate a sample
            scores: list[float] = []
            for ex in examples[-20:]:  # evaluate last 20
                try:
                    score = await self.evaluator.evaluate(
                        query=ex.get("query", ""),
                        response=ex.get("response", ""),
                    )
                    scores.append(score.overall)
                except Exception:  # noqa: BLE001
                    pass

            avg_score = sum(scores) / len(scores) if scores else 0.0
            span.set_attribute("learning.avg_score", avg_score)

            # 3. Detect patterns and emit strategy updates
            updates = self._detect_strategy_updates(examples, avg_score)

            # 4. Persist strategy
            await self._save_strategy(updates)

            # 5. Update RL bandit with per-example rewards
            await self._update_rl_bandit(examples, scores)

            # 6. Trigger memory evolution pipeline
            await self._run_memory_evolution(examples)

            # 7. Meta-learning: evolve the policy itself
            if accepted >= 10:
                await self._run_meta_learning(examples, avg_score)

            self.flywheel.clear()

            logger.info(
                "Learning cycle complete",
                cycle=cycle_id,
                examples=accepted,
                avg_score=round(avg_score, 3),
                updates=len(updates),
            )
            return LearningCycle(
                cycle_id=cycle_id,
                examples_processed=accepted,
                avg_score=avg_score,
                strategy_updates=[u.key for u in updates],
            )

    def _detect_strategy_updates(
        self, examples: list[dict[str, Any]], avg_score: float
    ) -> list[StrategyUpdate]:
        updates: list[StrategyUpdate] = []

        # Heuristic: if avg score drops below 0.6, increase reasoning depth
        current_depth = self._strategy.get("reasoning_depth", "standard")
        if avg_score < 0.6 and current_depth != "deep":
            updates.append(StrategyUpdate(
                key="reasoning_depth",
                old_value=current_depth,
                new_value="deep",
                reason=f"Low avg score {avg_score:.2f} — increasing reasoning depth",
            ))
            self._strategy["reasoning_depth"] = "deep"

        # Heuristic: if avg score is high, reduce unnecessary complexity
        if avg_score > 0.85 and current_depth == "deep":
            updates.append(StrategyUpdate(
                key="reasoning_depth",
                old_value=current_depth,
                new_value="standard",
                reason=f"High avg score {avg_score:.2f} — reverting to standard depth",
            ))
            self._strategy["reasoning_depth"] = "standard"

        return updates

    async def _save_strategy(self, updates: list[StrategyUpdate]) -> None:
        if not updates:
            return
        r = await get_memory_redis()
        await r.set(
            LEARNING_KEY,
            json.dumps({
                "strategy": self._strategy,
                "updates": [
                    {"key": u.key, "value": u.new_value, "reason": u.reason}
                    for u in updates
                ],
                "ts": time.time(),
            }),
        )
        # Push strategy updates to PolicyEngine singleton at runtime
        self._push_to_policy_engine()

    def _push_to_policy_engine(self) -> None:
        """Inject current strategy into the module-level PolicyEngine singleton."""
        try:
            from kernel.policy.engine import PolicyEngine
            # Access the orchestrator's policy engine if available
            from kernel.orchestrator import CognitiveOrchestrator
            # Walk known singletons — best-effort, non-critical
            import gc
            for obj in gc.get_referrers(PolicyEngine):
                if isinstance(obj, PolicyEngine):
                    obj.update_strategy(self._strategy)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not push strategy to PolicyEngine", error=str(exc))

    async def _update_rl_bandit(
        self, examples: list[dict[str, Any]], scores: list[float]
    ) -> None:
        """Push per-example rewards into the RLPolicyEngine bandit."""
        try:
            rl = self._get_rl_engine()
            for ex, score in zip(examples[-len(scores):], scores):
                action = ex.get("route", "REASON_COT")
                latency = float(ex.get("latency", 1.0))
                feedback = float(ex.get("user_feedback", 0.0))
                await rl.update(
                    action=action,
                    correctness=score,
                    latency=latency,
                    user_feedback=feedback,
                )
            logger.debug("RL bandit updated", n=len(scores))
        except Exception as exc:  # noqa: BLE001
            logger.warning("RL bandit update failed", error=str(exc))

    async def _run_memory_evolution(
        self, examples: list[dict[str, Any]]
    ) -> None:
        """Run memory evolution if enough high-quality examples."""
        try:
            good = [e for e in examples if float(e.get("score", 0)) >= 0.7]
            if len(good) >= 5:
                evo = self._get_memory_evolution()
                pattern, skill = await evo.evolve(good)
                if skill:
                    logger.info("Memory evolution: new skill", name=skill.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory evolution failed", error=str(exc))

    async def _run_meta_learning(
        self, examples: list[dict[str, Any]], avg_score: float
    ) -> None:
        """Run meta-learning policy evolution cycle."""
        try:
            from evolution.meta_learning.meta_learner import meta_learner
            perf_data = [
                {
                    "correctness": e.get("score", avg_score),
                    "latency": e.get("latency", 1.0),
                    "cost": e.get("cost", 0.01),
                }
                for e in examples
            ]
            result = await meta_learner.run_cycle(perf_data)
            logger.info(
                "Meta-learning cycle",
                active=result["active_policy"],
                score=round(result["score"], 3),
                generation=result["generation"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Meta-learning failed", error=str(exc))

    async def load_strategy(self) -> dict[str, Any]:
        """Load persisted strategy from Redis."""
        r = await get_memory_redis()
        raw = await r.get(LEARNING_KEY)
        if raw:
            data = json.loads(raw)
            self._strategy = data.get("strategy", {})
        return self._strategy


learning_engine = LearningEngine()
