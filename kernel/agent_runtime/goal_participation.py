"""Goal participation graph — aggregate AgentContribution into goal progress."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from kernel.agent_runtime.contribution import AgentContribution, GoalContribution


class GoalParticipationEdge(BaseModel):
    capability_type: str
    agent_type: str
    goal_id: str
    supports_goal: bool
    goal_delta: float
    confidence: float
    next_goal_hint: str = ""


class GoalParticipationGraph(BaseModel):
    """Per-turn graph of how agents advanced (or blocked) goals."""

    root_goal_id: str
    edges: list[GoalParticipationEdge] = Field(default_factory=list)
    aggregate_delta: float = 0.0
    satisfied: bool = False
    version: str = "goal_participation_v1"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "goal_participation": self.model_dump(mode="json"),
            "goal_participation_version": self.version,
        }


def merge_goal_contributions(
    contributions: list[AgentContribution],
    *,
    root_goal_id: str,
    satisfaction_threshold: float = 0.65,
) -> GoalParticipationGraph:
    edges: list[GoalParticipationEdge] = []
    delta_sum = 0.0
    for c in contributions:
        g = c.goal
        if not g or not g.goal_id:
            continue
        edges.append(
            GoalParticipationEdge(
                capability_type=c.capability_type,
                agent_type=c.agent_type,
                goal_id=g.goal_id,
                supports_goal=g.supports_goal,
                goal_delta=g.goal_delta,
                confidence=g.confidence,
                next_goal_hint=g.next_goal_hint,
            )
        )
        delta_sum += g.goal_delta

    avg_delta = delta_sum / max(1, len(edges))
    confidences = [e.confidence for e in edges if e.supports_goal]
    satisfied = bool(confidences) and (sum(confidences) / len(confidences)) >= satisfaction_threshold

    return GoalParticipationGraph(
        root_goal_id=root_goal_id,
        edges=edges,
        aggregate_delta=avg_delta,
        satisfied=satisfied,
    )


def contributions_from_agent_results(
    results: list[Any],
    *,
    root_goal_id: str,
    goal_description: str = "",
    trace_id: str = "",
) -> list[AgentContribution]:
    from kernel.agent_runtime.contribution import contribution_from_agent_result

    out: list[AgentContribution] = []
    for r in results or []:
        out.append(
            contribution_from_agent_result(
                r,
                goal_id=root_goal_id,
                goal_description=goal_description,
                trace_id=trace_id,
            )
        )
    return out