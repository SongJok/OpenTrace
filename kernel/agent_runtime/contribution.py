"""AgentContribution / GoalContribution / MemoryContribution — goal-aware agent outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from kernel.agent_runtime.manifest import get_manifest
from kernel.agent_runtime.unified_evidence import UnifiedEvidence, normalize_evidence_list

SupportLevel = Literal["supports", "neutral", "contradicts", "unknown"]


class GoalContribution(BaseModel):
    goal_id: str
    goal_description: str = ""
    confidence: float = 0.0
    supports_goal: bool = False
    goal_delta: float = 0.0
    next_goal_hint: str = ""
    support_level: SupportLevel = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryContribution(BaseModel):
    """Signals for memory fabric / TMS (not raw memory writes)."""

    should_persist: bool = False
    memory_keys: list[str] = Field(default_factory=list)
    salience: float = 0.0
    supersede_ids: list[str] = Field(default_factory=list)
    contradiction_with: list[str] = Field(default_factory=list)
    policy_tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentContribution(BaseModel):
    """Primary agent output for Agent Runtime V3 (wraps legacy AgentResult)."""

    task_id: str
    capability_type: str
    agent_type: str
    status: str
    content: str = ""
    confidence: float = 0.5
    unified_evidence: list[UnifiedEvidence] = Field(default_factory=list)
    goal: GoalContribution | None = None
    memory: MemoryContribution | None = None
    acquisition_cost: float = 0.0
    latency_ms: int = 0
    trace: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    legacy_agent_result: dict[str, Any] = Field(default_factory=dict)

    def to_agent_result_dict(self) -> dict[str, Any]:
        """Serialize for Agent Bus / Redis compatibility."""
        base = dict(self.legacy_agent_result)
        base.update(
            {
                "task_id": self.task_id,
                "agent_type": self.agent_type,
                "status": self.status,
                "content": self.content,
                "confidence": self.confidence,
                "error": self.error,
                "metadata": {
                    **(base.get("metadata") or {}),
                    "capability_type": self.capability_type,
                    "agent_runtime_v3": True,
                    "goal_contribution": self.goal.model_dump(mode="json") if self.goal else None,
                    "memory_contribution": self.memory.model_dump(mode="json") if self.memory else None,
                    "unified_evidence": [u.model_dump(mode="json") for u in self.unified_evidence],
                    "agent_trace": self.trace,
                    "acquisition_cost": self.acquisition_cost,
                    "latency_ms": self.latency_ms,
                },
                "evidence": [u.model_dump(mode="json") for u in self.unified_evidence],
                "evidence_objects": [
                    u.to_runtime_evidence().model_dump(mode="json") for u in self.unified_evidence
                ],
            }
        )
        return base


def _score_goal_support(
    *,
    confidence: float,
    status: str,
    evidence: list[UnifiedEvidence],
) -> tuple[bool, float, SupportLevel]:
    if status not in ("success", "ok", "done"):
        return False, -0.1, "contradicts"
    avg_conf = confidence
    if evidence:
        avg_conf = sum(e.confidence for e in evidence) / max(1, len(evidence))
    delta = max(-1.0, min(1.0, (avg_conf - 0.5) * 2.0))
    supports = avg_conf >= 0.45
    level: SupportLevel = "supports" if supports and avg_conf >= 0.55 else (
        "neutral" if supports else "contradicts" if status == "error" else "unknown"
    )
    return supports, delta, level


def build_goal_contribution(
    *,
    goal_id: str,
    goal_description: str = "",
    confidence: float,
    status: str,
    unified_evidence: list[UnifiedEvidence],
    next_goal_hint: str = "",
) -> GoalContribution:
    supports, delta, level = _score_goal_support(
        confidence=confidence, status=status, evidence=unified_evidence
    )
    return GoalContribution(
        goal_id=goal_id,
        goal_description=goal_description,
        confidence=confidence,
        supports_goal=supports,
        goal_delta=delta,
        next_goal_hint=next_goal_hint,
        support_level=level,
        evidence_ids=[e.evidence_id for e in unified_evidence],
    )


def build_memory_contribution(
    *,
    unified_evidence: list[UnifiedEvidence],
    status: str,
    confidence: float,
) -> MemoryContribution:
    persist = status in ("success", "ok", "done") and confidence >= 0.55
    salience = min(1.0, max(0.0, confidence))
    contradictions: list[str] = []
    for u in unified_evidence:
        contradictions.extend(u.contradiction_links)
    return MemoryContribution(
        should_persist=persist,
        memory_keys=[u.evidence_id for u in unified_evidence if u.confidence >= 0.5],
        salience=salience,
        contradiction_with=list(dict.fromkeys(contradictions)),
        policy_tags=["agent_runtime_v3"],
    )


def contribution_from_agent_result(
    result: Any,
    *,
    goal_id: str = "",
    goal_description: str = "",
    capability_type: str = "",
    trace_id: str = "",
    latency_ms: int = 0,
    next_goal_hint: str = "",
) -> AgentContribution:
    from agents.base import AgentResult

    manifest = get_manifest()
    agent_type = str(getattr(result, "agent_type", "") or "")
    resolved_cap = capability_type or manifest.capability_type_for_agent(agent_type)
    status = str(getattr(result, "status", "error"))
    conf = float(getattr(result, "confidence", 0.0) or 0.0)

    raw_evidence: list[Any] = list(getattr(result, "evidence_objects", None) or [])
    if not raw_evidence:
        raw_evidence = list(getattr(result, "evidence", None) or [])
    if not raw_evidence and getattr(result, "content", ""):
        raw_evidence = [result]

    unified = normalize_evidence_list(
        raw_evidence,
        goal_id=goal_id,
        capability_type=resolved_cap,
        trace_id=trace_id,
    )

    goal = None
    if goal_id:
        goal = build_goal_contribution(
            goal_id=goal_id,
            goal_description=goal_description,
            confidence=conf,
            status=status,
            unified_evidence=unified,
            next_goal_hint=next_goal_hint,
        )

    memory = build_memory_contribution(
        unified_evidence=unified, status=status, confidence=conf
    )

    legacy: dict[str, Any] = {}
    if isinstance(result, AgentResult):
        legacy = result.model_dump(mode="json")
    elif hasattr(result, "model_dump"):
        legacy = result.model_dump(mode="json")

    md = dict(legacy.get("metadata") or getattr(result, "metadata", None) or {})
    cost = float(md.get("acquisition_cost") or md.get("cost") or getattr(result, "acquisition_cost", 0) or 0.0)

    return AgentContribution(
        task_id=str(getattr(result, "task_id", "")),
        capability_type=resolved_cap,
        agent_type=agent_type,
        status=status,
        content=str(getattr(result, "content", "") or ""),
        confidence=conf,
        unified_evidence=unified,
        goal=goal,
        memory=memory,
        acquisition_cost=cost,
        latency_ms=latency_ms,
        trace=dict(getattr(result, "agent_trace", None) or md.get("agent_trace") or {}),
        error=getattr(result, "error", None),
        legacy_agent_result=legacy,
    )