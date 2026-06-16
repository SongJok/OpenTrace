"""
Runtime grounding system — shared models for User / Environment / Capability /
Risk / Temporal / Memory / Execution.

Lightweight in-process store; Executive and Supervisor read/write projections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class UserModelSlice:
    session_id: str = ""
    preferences: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvironmentModelSlice:
    intent_category: str = "general"
    sub_goal_count: int = 0
    protected_intent: str = ""


@dataclass
class CapabilityModelSlice:
    active_capabilities: list[str] = field(default_factory=list)
    risk_tier: str = "low"


@dataclass
class RiskModelSlice:
    level: str = "low"
    score: float = 0.0
    factors: list[str] = field(default_factory=list)


@dataclass
class TemporalModelSlice:
    turn_index: int = 0
    last_request_id: str = ""


@dataclass
class MemoryModelSlice:
    fabric_refs: list[str] = field(default_factory=list)
    goal_id: str = ""


@dataclass
class ExecutionModelSlice:
    phase: str = "init"
    replanned: bool = False


@dataclass
class GoalModelSlice:
    root_goal_id: str = ""
    active_states: dict[str, str] = field(default_factory=dict)
    blocked_count: int = 0
    version: int = 0


@dataclass
class RuntimeGroundingState:
    user: UserModelSlice = field(default_factory=UserModelSlice)
    environment: EnvironmentModelSlice = field(default_factory=EnvironmentModelSlice)
    capability: CapabilityModelSlice = field(default_factory=CapabilityModelSlice)
    risk: RiskModelSlice = field(default_factory=RiskModelSlice)
    temporal: TemporalModelSlice = field(default_factory=TemporalModelSlice)
    memory: MemoryModelSlice = field(default_factory=MemoryModelSlice)
    execution: ExecutionModelSlice = field(default_factory=ExecutionModelSlice)
    goal: GoalModelSlice = field(default_factory=GoalModelSlice)
    memory_refs: list[str] = field(default_factory=list)
    world_state_id: str = ""
    parent_world_state_id: str = ""
    turn_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": {
                "session_id": self.user.session_id,
                "preferences": dict(self.user.preferences),
            },
            "environment": {
                "intent_category": self.environment.intent_category,
                "sub_goal_count": self.environment.sub_goal_count,
                "protected_intent": self.environment.protected_intent[:200],
            },
            "capability": {
                "active": list(self.capability.active_capabilities),
                "risk_tier": self.capability.risk_tier,
            },
            "risk": {
                "level": self.risk.level,
                "score": self.risk.score,
                "factors": self.risk.factors,
            },
            "temporal": {
                "turn_index": self.temporal.turn_index,
                "last_request_id": self.temporal.last_request_id,
            },
            "memory": {
                "fabric_refs": list(self.memory.fabric_refs),
                "goal_id": self.memory.goal_id,
            },
            "execution": {
                "phase": self.execution.phase,
                "replanned": self.execution.replanned,
            },
            "goal": {
                "root_goal_id": self.goal.root_goal_id,
                "active_states": dict(self.goal.active_states),
                "blocked_count": self.goal.blocked_count,
                "version": self.goal.version,
            },
            "memory_refs": list(self.memory_refs),
            "world_state_id": self.world_state_id,
            "parent_world_state_id": self.parent_world_state_id,
            "turn_index": self.turn_index,
        }


_store: dict[str, RuntimeGroundingState] = {}


def get_grounding(session_id: str) -> RuntimeGroundingState:
    sid = session_id or "default"
    if sid not in _store:
        _store[sid] = RuntimeGroundingState(user=UserModelSlice(session_id=sid))
    return _store[sid]


def project_from_context(ctx: Any) -> RuntimeGroundingState:
    sid = str(getattr(ctx, "session_id", "") or "default")
    state = get_grounding(sid)
    md = getattr(ctx, "metadata", None) or {}
    prefs = getattr(ctx, "user_preferences", None) or []
    state.user.preferences = (
        {"items": prefs} if isinstance(prefs, list) else dict(prefs or {})
    )
    state.capability.active_capabilities = list(
        getattr(ctx, "allowed_capabilities", None) or []
    )
    gg = md.get("goal_graph") or {}
    goals = gg.get("goals") if isinstance(gg, dict) else []
    sub_count = 0
    if isinstance(goals, list):
        root = str(gg.get("root_goal_id", "") or "")
        sub_count = sum(
            1 for g in goals if isinstance(g, dict) and g.get("parent_id") == root
        )
    state.environment.intent_category = str(
        gg.get("intent_category", "")
        or getattr(ctx, "task_type", None)
        or "general"
    )
    state.environment.sub_goal_count = sub_count
    state.environment.protected_intent = str(
        gg.get("protected_intent", "") or getattr(ctx, "protected_intent", "") or ""
    )
    root_id = str(gg.get("root_goal_id", "") or getattr(ctx, "request_id", ""))
    state.memory.goal_id = root_id
    state.goal.root_goal_id = root_id
    if isinstance(goals, list):
        active: dict[str, str] = {}
        blocked = 0
        for g in goals:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("goal_id", "") or "")
            st = str((g.get("metadata") or {}).get("lifecycle_state", "") or "")
            if gid and st:
                active[gid] = st
            if st == "blocked":
                blocked += 1
        state.goal.active_states = active
        state.goal.blocked_count = blocked
        state.goal.version = int(md.get("goal_world_version", state.goal.version) or 0)
    fabric = md.get("fabric_graph_live") or md.get("fabric_graph_seeded") or {}
    if isinstance(fabric, dict):
        nodes = fabric.get("nodes") or []
        state.memory.fabric_refs = [
            str(n.get("id", "")) for n in nodes if isinstance(n, dict) and n.get("id")
        ][:32]
    state.memory_refs = list(state.memory.fabric_refs)
    state.temporal.last_request_id = str(getattr(ctx, "request_id", "") or "")
    state.temporal.turn_index = int(md.get("turn_index", state.temporal.turn_index) or 0)
    state.execution.phase = str(md.get("runtime_phase", "init"))
    state.execution.replanned = bool(md.get("refine_replan"))
    if md.get("adaptive_risk"):
        ar = md["adaptive_risk"]
        state.risk.level = ar.get("level", "low")
        state.risk.score = float(ar.get("score", 0.0))
        state.risk.factors = list(ar.get("factors") or [])
    bump_world_state_version(state, request_id=str(getattr(ctx, "request_id", "") or ""))
    return state


def bump_world_state_version(
    state: RuntimeGroundingState, *, request_id: str = ""
) -> RuntimeGroundingState:
    import uuid

    state.parent_world_state_id = state.world_state_id or ""
    state.world_state_id = str(uuid.uuid4())
    state.turn_index = int(state.turn_index or state.temporal.turn_index or 0) + 1
    state.temporal.turn_index = state.turn_index
    if request_id:
        state.temporal.last_request_id = request_id
    state.goal.version = int(state.goal.version or 0) + 1
    return state


def attach_world_state_to_context(ctx: Any, state: RuntimeGroundingState) -> None:
    """Write grounding snapshot + lineage onto ctx.metadata for artifact/replay."""
    ctx.metadata = getattr(ctx, "metadata", None) or {}
    d = state.to_dict()
    ctx.metadata["runtime_grounding"] = d
    ctx.metadata["world_state_id"] = state.world_state_id
    ctx.metadata["parent_world_state_id"] = state.parent_world_state_id
    ctx.metadata["goal_world_version"] = state.goal.version


def _world_state_redis_key(session_id: str) -> str:
    return f"world_state:{session_id or 'default'}"


async def persist_world_state(session_id: str, state: RuntimeGroundingState) -> None:
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_world_state_persist_enabled", False)):
            return
        from infra.cache.redis_client import get_memory_redis

        r = await get_memory_redis()
        import json

        await r.setex(
            _world_state_redis_key(session_id),
            86400,
            json.dumps(state.to_dict(), ensure_ascii=False),
        )
    except Exception as exc:
        logger.warning(
            "world_state_persist_failed",
            session_id=session_id,
            error=str(exc),
        )


async def load_persisted_world_state(session_id: str) -> dict[str, Any] | None:
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_world_state_persist_enabled", False)):
            return None
        from infra.cache.redis_client import get_memory_redis

        r = await get_memory_redis()
        raw = await r.get(_world_state_redis_key(session_id))
        if not raw:
            return None
        import json

        return json.loads(raw)
    except Exception as exc:
        logger.warning(
            "world_state_load_failed",
            session_id=session_id,
            error=str(exc),
        )
        return None


def merge_persisted_into_grounding(session_id: str, persisted: dict[str, Any]) -> None:
    """Restore last persisted world state into in-process store before projecting."""
    if not persisted:
        return
    sid = session_id or "default"
    state = get_grounding(sid)
    state.world_state_id = str(persisted.get("world_state_id", "") or state.world_state_id)
    state.parent_world_state_id = str(
        persisted.get("parent_world_state_id", "") or state.parent_world_state_id
    )
    state.turn_index = int(persisted.get("turn_index", state.turn_index) or 0)
    goal = persisted.get("goal") or {}
    if isinstance(goal, dict):
        state.goal.root_goal_id = str(goal.get("root_goal_id", "") or state.goal.root_goal_id)
        state.goal.active_states = dict(goal.get("active_states") or {})
        state.goal.blocked_count = int(goal.get("blocked_count", 0) or 0)
        state.goal.version = int(goal.get("version", state.goal.version) or 0)
    exec_slice = persisted.get("execution") or {}
    if isinstance(exec_slice, dict):
        state.execution.phase = str(exec_slice.get("phase", state.execution.phase) or state.execution.phase)


async def hydrate_world_state_for_session(session_id: str) -> dict[str, Any] | None:
    """Load Redis world state into in-process grounding; return persisted dict if any."""
    persisted = await load_persisted_world_state(session_id)
    if persisted:
        merge_persisted_into_grounding(session_id, persisted)
    return persisted
    return state