"""Behavioral runtime contracts (state transitions, mutations)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class RuntimePhase(str, Enum):
    INIT = "init"
    REWRITE = "rewrite"
    UNDERSTAND = "understand"
    PLAN = "plan"
    WAITING = "waiting"
    EXECUTE = "execute"
    EVIDENCE = "evidence"
    FUSION = "fusion"
    REPLANNING = "replanning"
    CRITIC = "critic"
    COMPLETE = "complete"
    ARCHIVED = "archived"
    DONE = "done"

_VALID_TRANSITIONS: dict[RuntimePhase, set[RuntimePhase]] = {
    RuntimePhase.INIT: {
        RuntimePhase.REWRITE,
        RuntimePhase.UNDERSTAND,
        RuntimePhase.PLAN,
        RuntimePhase.EXECUTE,
    },
    RuntimePhase.REWRITE: {RuntimePhase.UNDERSTAND, RuntimePhase.PLAN},
    RuntimePhase.UNDERSTAND: {RuntimePhase.PLAN},
    RuntimePhase.PLAN: {
        RuntimePhase.EXECUTE,
        RuntimePhase.PLAN,
        RuntimePhase.WAITING,
        RuntimePhase.REPLANNING,
    },
    RuntimePhase.WAITING: {RuntimePhase.EXECUTE, RuntimePhase.PLAN, RuntimePhase.REPLANNING},
    RuntimePhase.EXECUTE: {
        RuntimePhase.EVIDENCE,
        RuntimePhase.PLAN,
        RuntimePhase.EXECUTE,
        RuntimePhase.WAITING,
        RuntimePhase.REPLANNING,
    },
    RuntimePhase.EVIDENCE: {RuntimePhase.FUSION, RuntimePhase.EXECUTE},
    RuntimePhase.FUSION: {RuntimePhase.CRITIC, RuntimePhase.DONE, RuntimePhase.COMPLETE},
    RuntimePhase.REPLANNING: {RuntimePhase.PLAN, RuntimePhase.EXECUTE},
    RuntimePhase.CRITIC: {RuntimePhase.DONE, RuntimePhase.COMPLETE, RuntimePhase.REPLANNING},
    RuntimePhase.COMPLETE: {RuntimePhase.DONE, RuntimePhase.COMPLETE, RuntimePhase.ARCHIVED},
    RuntimePhase.ARCHIVED: {RuntimePhase.DONE},
    RuntimePhase.DONE: set(),
}


def assert_phase_transition(current: str, next_phase: str) -> bool:
    try:
        cur = RuntimePhase(current)
        nxt = RuntimePhase(next_phase)
    except ValueError:
        return True
    allowed = _VALID_TRANSITIONS.get(cur, set())
    return nxt in allowed or nxt == cur


def validate_runtime_mutation(field: str, old: Any, new: Any) -> list[str]:
    violations: list[str] = []
    if field == "goal_graph" and old and not new:
        violations.append("goal_graph_cleared")
    return violations


def enforce_phase_transition(current: str, next_phase: str, *, strict: bool = False) -> list[str]:
    """Return violation messages; if strict and non-empty, caller should abort."""
    if assert_phase_transition(current, next_phase):
        return []
    return [f"invalid_phase_transition:{current}->{next_phase}"]


@dataclass
class ReplayContract:
    """Minimum fields required for deterministic replay audit."""

    request_id: str
    session_id: str
    root_goal_id: str
    artifact_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)


def validate_replay_contract(contract: ReplayContract) -> list[str]:
    violations: list[str] = []
    if not contract.request_id:
        violations.append("missing_request_id")
    if not contract.root_goal_id:
        violations.append("missing_root_goal_id")
    return violations


def validate_evidence_contract(
    evidence_ids: list[str],
    *,
    min_count: int = 0,
) -> list[str]:
    """Return violations if evidence set does not meet contract."""
    violations: list[str] = []
    if len(evidence_ids) < min_count:
        violations.append(f"evidence_count_below_min:{len(evidence_ids)}<{min_count}")
    return violations


def validate_capability_execution_contract(
    capability_name: str,
    allowed: list[str],
    disallowed: list[str] | None = None,
) -> list[str]:
    """Return violations if capability is not permitted for this turn."""
    violations: list[str] = []
    dis = disallowed or []
    if capability_name in dis:
        violations.append(f"capability_disallowed:{capability_name}")
    if allowed and capability_name not in allowed:
        violations.append(f"capability_not_in_allowlist:{capability_name}")
    return violations


def validate_evidence_contract(
    evidence_ids: list[str],
    *,
    min_count: int = 0,
    require_goal_binding: bool = False,
    root_goal_id: str = "",
) -> list[str]:
    """Evidence integrity contract for fusion / artifact phases."""
    violations: list[str] = []
    if len(evidence_ids) < min_count:
        violations.append(f"evidence_count_below_min:{len(evidence_ids)}<{min_count}")
    if require_goal_binding and not root_goal_id:
        violations.append("evidence_missing_goal_binding")
    return violations


def validate_capability_execution_contract(
    capability_name: str,
    allowed: list[str] | None,
    disallowed: list[str] | None,
) -> list[str]:
    violations: list[str] = []
    if disallowed and capability_name in disallowed:
        violations.append(f"capability_disallowed:{capability_name}")
    if allowed and capability_name not in allowed:
        violations.append(f"capability_not_in_allowlist:{capability_name}")
    return violations