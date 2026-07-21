"""Shared Evidence helpers for tier-1 agents (Agent Runtime V3)."""

from __future__ import annotations

from typing import Any

from agents.base import AgentResult
from kernel.runtime.objects import Evidence


def evidence_from_agent_result(result: AgentResult) -> list[Evidence]:
    """Prefer structured evidence_objects; else wrap legacy dict evidence or content."""
    if result.evidence_objects:
        return list(result.evidence_objects)
    out: list[Evidence] = []
    for item in result.evidence or []:
        if isinstance(item, Evidence):
            out.append(item)
            continue
        if isinstance(item, dict):
            from kernel.runtime.objects import Provenance

            payload = item.get("payload", item)
            text = payload if isinstance(payload, str) else str(payload)
            st = str(item.get("source_type", "agent"))
            out.append(
                Evidence(
                    content=text[:8000],
                    content_type=str(item.get("content_type", "text")),
                    provenance=Provenance(
                        source=str(item.get("source", result.agent_type)),
                        source_type=st,
                        confidence=float(item.get("credibility_score", result.confidence)),
                    ),
                    credibility_score=float(item.get("credibility_score", result.confidence)),
                    relevance_score=float(item.get("relevance_score", 0.5)),
                    metadata=dict(item),
                )
            )
    if not out and result.content and result.status in ("success", "ok", "done"):
        from kernel.runtime.objects import Provenance

        out.append(
            Evidence(
                content=result.content,
                content_type="text",
                provenance=Provenance(
                    source=result.agent_type,
                    source_type="agent",
                    confidence=result.confidence,
                ),
                credibility_score=result.confidence,
                relevance_score=0.5,
                metadata={"task_id": result.task_id, **(result.metadata or {})},
            )
        )
    return out


def attach_evidence_objects(result: AgentResult) -> AgentResult:
    """Populate evidence_objects on AgentResult for contribution normalization."""
    objs = evidence_from_agent_result(result)
    if objs:
        result.evidence_objects = objs
    return result