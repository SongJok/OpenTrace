"""
Admin router — system management endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter

from evolution.learning.learning import learning_engine
from infra.observability.logger import get_logger
from tools.registry.registry import registry

logger = get_logger(__name__)
router = APIRouter()


@router.get("/admin/tools")
async def list_tools() -> dict:
    """List all registered tools."""
    return {"tools": registry.list_all()}


@router.post("/admin/learning/cycle")
async def run_learning_cycle() -> dict:
    """Trigger a learning cycle manually."""
    cycle = await learning_engine.run_cycle()
    return {
        "cycle_id": cycle.cycle_id,
        "examples_processed": cycle.examples_processed,
        "avg_score": round(cycle.avg_score, 4),
        "strategy_updates": cycle.strategy_updates,
    }


@router.get("/admin/strategy")
async def get_strategy() -> dict:
    """Return current learned strategy."""
    strategy = await learning_engine.load_strategy()
    return {"strategy": strategy}


@router.get("/admin/bandit/stats")
async def get_bandit_stats() -> dict:
    """Return RL bandit arm statistics and total pulls."""
    from kernel.policy.rl_engine import rl_policy_engine
    stats = rl_policy_engine.bandit.get_stats()
    return {
        "total_pulls": rl_policy_engine.bandit._total_pulls,
        "arms": stats,
    }


@router.post("/admin/bandit/reset")
async def reset_bandit() -> dict:
    """Reset bandit arm statistics (for testing / retraining)."""
    from kernel.policy.bandit import BanditPolicy
    from kernel.policy.rl_engine import rl_policy_engine
    rl_policy_engine.bandit = BanditPolicy(mode="ucb1")
    return {"status": "bandit reset"}


@router.get("/admin/memory/patterns")
async def get_memory_patterns() -> dict:
    """Return all evolved memory patterns and skills."""
    from memory.evolution.evolution import MemoryEvolution
    evo = MemoryEvolution()
    patterns, skills = await evo.load_all()
    return {
        "patterns": [
            {"id": p.pattern_id, "description": p.description,
             "strategy": p.strategy, "weight": p.weight}
            for p in patterns
        ],
        "skills": [
            {"id": s.skill_id, "name": s.name,
             "description": s.description,
             "triggers": s.trigger_conditions, "weight": s.weight}
            for s in skills
        ],
    }


@router.get("/admin/memory/weak")
async def get_weak_memories() -> dict:
    """Return memory IDs below reinforcement threshold (candidates for pruning)."""
    from memory.evolution.evolution import MemoryReinforcement
    pruned = await MemoryReinforcement().prune_weak(threshold=0.1)
    return {"weak_memory_ids": pruned, "count": len(pruned)}


@router.get("/admin/gateway/health")
async def gateway_health() -> dict:
    """Return ModelGateway circuit-breaker status per role."""
    from model.model_gateway.gateway import get_model_gateway, LLMRole
    gw = get_model_gateway()
    status = {}
    for role in LLMRole:
        cb = gw._circuit_breakers.get(role.value)
        if cb:
            status[role.value] = {
                "state": cb.state,
                "failures": cb.failure_count,
                "last_failure": cb.last_failure_time,
            }
        else:
            status[role.value] = {"state": "closed", "failures": 0}
    return {"circuit_breakers": status}


@router.get("/admin/meta/policies")
async def get_meta_policies() -> dict:
    """Return all meta-learning policy candidates and the active one."""
    from evolution.meta_learning.meta_learner import meta_learner
    await meta_learner._load_policies()
    policies = [
        {
            "id": p.policy_id, "name": p.name,
            "score": round(p.score, 4), "generation": p.generation,
            "is_active": p.is_active, "eval_count": p.eval_count,
        }
        for p in meta_learner._policies
    ]
    active_rules = await meta_learner.get_active_rules()
    return {"policies": policies, "active_rules": active_rules}


@router.post("/admin/meta/cycle")
async def run_meta_cycle() -> dict:
    """Manually trigger a meta-learning evolution cycle."""
    from evolution.meta_learning.meta_learner import meta_learner
    result = await meta_learner.run_cycle(performance_data=[])
    return result


@router.get("/admin/market/agents")
async def list_market_agents() -> dict:
    """Return all registered agents and their reputation."""
    from agent_runtime.market.market import agent_market
    return {"agents": agent_market.list_agents()}


@router.post("/admin/selfplay/run")
async def run_self_play(n: int = 3, difficulty: float = 0.6) -> dict:
    """Run N self-play episodes and feed results into the learning loop."""
    from evolution.self_play.self_play import self_play
    episodes = await self_play.run_batch(n=n, difficulty=difficulty)
    learn_result = await self_play.learn(episodes)
    return {
        "episodes": [
            {
                "id": ep.episode_id, "domain": ep.domain,
                "reward": round(ep.reward, 3), "action": ep.action,
                "task": ep.task[:80],
            }
            for ep in episodes
        ],
        "learn": learn_result,
    }
