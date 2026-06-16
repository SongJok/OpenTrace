"""Goal transition events — audit trail for lifecycle mutations."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from kernel.goal.state_machine import GoalLifecycleState


@dataclass
class GoalTransition:
    transition_id: str
    goal_id: str
    from_state: str
    to_state: str
    reason: str = ""
    ref_type: str = ""
    ref_id: str = ""
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def record_goal_transition(
    goal: Any,
    *,
    from_state: GoalLifecycleState | str,
    to_state: GoalLifecycleState | str,
    reason: str = "",
    ref_type: str = "",
    ref_id: str = "",
    extra: dict[str, Any] | None = None,
) -> GoalTransition:
    """Append transition to goal.metadata['lifecycle_transitions'] (bounded)."""
    fs = from_state.value if isinstance(from_state, GoalLifecycleState) else str(from_state)
    ts = to_state.value if isinstance(to_state, GoalLifecycleState) else str(to_state)
    ev = GoalTransition(
        transition_id=str(uuid.uuid4()),
        goal_id=str(getattr(goal, "goal_id", "") or ""),
        from_state=fs,
        to_state=ts,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        metadata=dict(extra or {}),
    )
    goal.metadata = dict(goal.metadata or {})
    hist = list(goal.metadata.get("lifecycle_transitions") or [])
    hist.append(ev.to_dict())
    goal.metadata["lifecycle_transitions"] = hist[-32:]
    return ev


def graph_has_transition_rejection(graph: Any) -> bool:
    if not graph:
        return False
    for g in getattr(graph, "goals", []) or []:
        md = getattr(g, "metadata", None) or {}
        if md.get("lifecycle_transition_rejected"):
            return True
    return False