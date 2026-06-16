"""Unified Runtime Contribution — single contract for all capability providers.

All tier-1 providers (data, rag, web, tool, vision, skills, rules) should
normalize into ``RuntimeContribution`` so Goal / Evidence / Memory / World /
Governance consume one shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from kernel.agent_runtime.contribution import (
    AgentContribution,
    GoalContribution,
    MemoryContribution,
    contribution_from_agent_result,
)
from kernel.agent_runtime.unified_evidence import UnifiedEvidence, normalize_evidence_list
from kernel.agent_runtime.world_projection import WorldProjectionBundle


class WorldContribution(BaseModel):
    """Signals for world runtime (state deltas, not raw Redis writes)."""

    session_id: str = ""
    variable_updates: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    projection_hint: str = ""  # current | projected | counterfactual
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskSignal(BaseModel):
    code: str
    severity: float = 0.0
    message: str = ""
    source_capability: str = ""


class ContributionMetric(BaseModel):
    name: str
    value: float = 0.0
    unit: str = ""


class RuntimeContribution(BaseModel):
    """Canonical cognitive output for one capability invocation."""

    version: str = "runtime_contribution_v1"
    task_id: str = ""
    capability_type: str = ""
    agent_type: str = ""
    status: str = ""
    content: str = ""
    confidence: float = 0.5

    evidence: list[UnifiedEvidence] = Field(default_factory=list)
    goal_updates: list[GoalContribution] = Field(default_factory=list)
    memory_updates: list[MemoryContribution] = Field(default_factory=list)
    world_updates: list[WorldContribution] = Field(default_factory=list)
    risks: list[RiskSignal] = Field(default_factory=list)
    metrics: list[ContributionMetric] = Field(default_factory=list)

    acquisition_cost: float = 0.0
    latency_ms: int = 0
    trace: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    def to_agent_contribution(self) -> AgentContribution:
        """Bridge to Agent Runtime V3 (legacy bus / worker)."""
        goal = self.goal_updates[0] if self.goal_updates else None
        memory = self.memory_updates[0] if self.memory_updates else None
        return AgentContribution(
            task_id=self.task_id,
            capability_type=self.capability_type,
            agent_type=self.agent_type,
            status=self.status,
            content=self.content,
            confidence=self.confidence,
            unified_evidence=list(self.evidence),
            goal=goal,
            memory=memory,
            acquisition_cost=self.acquisition_cost,
            latency_ms=self.latency_ms,
            trace={
                **self.trace,
                "runtime_contribution": self.model_dump(mode="json"),
            },
            error=self.error,
            legacy_agent_result={},
        )

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "runtime_contribution_version": self.version,
            "runtime_contribution": self.model_dump(mode="json"),
        }


def _risks_from_contribution(agent: AgentContribution) -> list[RiskSignal]:
    risks: list[RiskSignal] = []
    if agent.status in ("error", "timeout", "failed"):
        risks.append(
            RiskSignal(
                code="capability_execution_failed",
                severity=0.7,
                message=str(agent.error or agent.status),
                source_capability=agent.capability_type,
            )
        )
    if agent.confidence < 0.35 and agent.status in ("success", "ok", "done"):
        risks.append(
            RiskSignal(
                code="low_confidence_answer",
                severity=0.4,
                message="capability returned low confidence",
                source_capability=agent.capability_type,
            )
        )
    for tag in (agent.memory.policy_tags if agent.memory else []):
        if tag.startswith("pii") or tag == "policy_violation":
            risks.append(
                RiskSignal(
                    code="policy_tag",
                    severity=0.6,
                    message=tag,
                    source_capability=agent.capability_type,
                )
            )
    return risks


def _metrics_from_contribution(agent: AgentContribution) -> list[ContributionMetric]:
    out = [
        ContributionMetric(name="confidence", value=agent.confidence),
        ContributionMetric(name="latency_ms", value=float(agent.latency_ms), unit="ms"),
        ContributionMetric(name="acquisition_cost", value=agent.acquisition_cost),
    ]
    if agent.goal:
        out.append(ContributionMetric(name="goal_delta", value=agent.goal.goal_delta))
    return out


def _world_from_metadata(md: dict[str, Any], session_id: str = "") -> list[WorldContribution]:
    updates: list[WorldContribution] = []
    wp = md.get("world_projection")
    if isinstance(wp, dict):
        try:
            bundle = WorldProjectionBundle.model_validate(wp)
            if bundle.counterfactual:
                updates.append(
                    WorldContribution(
                        session_id=session_id,
                        variable_updates=dict(bundle.counterfactual.variables),
                        assumptions=list(bundle.counterfactual.assumptions),
                        projection_hint="counterfactual",
                    )
                )
            elif bundle.current:
                updates.append(
                    WorldContribution(
                        session_id=session_id,
                        variable_updates=dict(bundle.current.variables),
                        projection_hint="current",
                    )
                )
        except Exception:
            pass
    ws = md.get("world_state") or md.get("world_snapshot")
    if isinstance(ws, dict) and ws and not updates:
        updates.append(
            WorldContribution(
                session_id=session_id,
                variable_updates=dict(ws),
                projection_hint="current",
            )
        )
    return updates


def runtime_contribution_from_agent_result(
    result: Any,
    *,
    goal_id: str = "",
    goal_description: str = "",
    capability_type: str = "",
    trace_id: str = "",
    latency_ms: int = 0,
    session_id: str = "",
    next_goal_hint: str = "",
) -> RuntimeContribution:
    agent = contribution_from_agent_result(
        result,
        goal_id=goal_id,
        goal_description=goal_description,
        capability_type=capability_type,
        trace_id=trace_id,
        latency_ms=latency_ms,
        next_goal_hint=next_goal_hint,
    )
    md = dict(getattr(result, "metadata", None) or {})
    goal_updates = [agent.goal] if agent.goal else []
    memory_updates = [agent.memory] if agent.memory else []
    return RuntimeContribution(
        task_id=agent.task_id,
        capability_type=agent.capability_type,
        agent_type=agent.agent_type,
        status=agent.status,
        content=agent.content,
        confidence=agent.confidence,
        evidence=list(agent.unified_evidence),
        goal_updates=goal_updates,
        memory_updates=memory_updates,
        world_updates=_world_from_metadata(md, session_id=session_id),
        risks=_risks_from_contribution(agent),
        metrics=_metrics_from_contribution(agent),
        acquisition_cost=agent.acquisition_cost,
        latency_ms=agent.latency_ms,
        trace=agent.trace,
        error=agent.error,
    )


def merge_runtime_contributions(
    contributions: list[RuntimeContribution],
    *,
    root_goal_id: str = "",
) -> RuntimeContribution:
    """Fold multiple capability contributions into one turn-level bundle."""
    if not contributions:
        return RuntimeContribution(
            task_id="merged",
            capability_type="fusion",
            agent_type="fusion",
            status="success",
        )
    evidence: list[UnifiedEvidence] = []
    goals: list[GoalContribution] = []
    memories: list[MemoryContribution] = []
    worlds: list[WorldContribution] = []
    risks: list[RiskSignal] = []
    metrics: list[ContributionMetric] = []
    contents: list[str] = []
    confs: list[float] = []
    status = "success"
    for c in contributions:
        evidence.extend(c.evidence)
        goals.extend(c.goal_updates)
        memories.extend(c.memory_updates)
        worlds.extend(c.world_updates)
        risks.extend(c.risks)
        metrics.extend(c.metrics)
        if c.content:
            contents.append(c.content)
        confs.append(c.confidence)
        if c.status not in ("success", "ok", "done"):
            status = c.status
    avg_conf = sum(confs) / max(1, len(confs))
    if root_goal_id and goals:
        # attach merged evidence ids to root goal view
        eids = [e.evidence_id for e in evidence]
        g0 = goals[0].model_copy(deep=True)
        g0.goal_id = root_goal_id
        g0.evidence_ids = list(dict.fromkeys(eids))
        goals = [g0, *goals[1:]]
    return RuntimeContribution(
        task_id="merged",
        capability_type="fusion",
        agent_type="runtime_merge",
        status=status,
        content="\n\n".join(contents)[:8000],
        confidence=avg_conf,
        evidence=normalize_evidence_list(evidence, goal_id=root_goal_id),
        goal_updates=goals,
        memory_updates=memories,
        world_updates=worlds,
        risks=risks,
        metrics=metrics,
    )