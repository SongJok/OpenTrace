"""UnifiedEvidence — normalize RAG / Web / Data / Tool / Memory into one bus schema."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from kernel.runtime.objects import Evidence, Provenance

SourceKind = Literal[
    "rag",
    "web",
    "data",
    "tool",
    "memory",
    "agent",
    "synthesized",
    "unknown",
]


class UnifiedEvidence(BaseModel):
    """Enterprise evidence unit for Evidence Bus, Fusion, Governance, Goal binding."""

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: SourceKind = "unknown"
    source_id: str = ""
    confidence: float = 0.5
    relevance: float = 0.5
    provenance: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    supporting_data: dict[str, Any] = Field(default_factory=dict)
    contradiction_links: list[str] = Field(default_factory=list)
    content: str = ""
    content_type: str = "text"
    goal_id: str = ""
    capability_type: str = ""
    trace_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_runtime_evidence(self) -> Evidence:
        prov = self.provenance or {}
        return Evidence(
            evidence_id=self.evidence_id,
            content=self.content,
            content_type=self.content_type,
            provenance=Provenance(
                source=self.source_id or str(prov.get("source", "")),
                source_type=str(prov.get("source_type", self.source_type)),
                confidence=float(prov.get("confidence", self.confidence)),
                trace_id=self.trace_id or str(prov.get("trace_id", "")),
            ),
            credibility_score=self.confidence,
            relevance_score=self.relevance,
            citations=list(self.citations),
            metadata={
                **self.metadata,
                "unified": True,
                "source_type": self.source_type,
                "claims": self.claims,
                "supporting_data": self.supporting_data,
                "contradiction_links": self.contradiction_links,
                "goal_id": self.goal_id,
                "capability_type": self.capability_type,
            },
            state="created",
        )


def _infer_source_kind(agent_type: str, metadata: dict[str, Any]) -> SourceKind:
    at = (agent_type or "").lower()
    md_type = str(metadata.get("evidence_source_type", "") or metadata.get("source_type", "")).lower()
    if md_type in ("rag", "web", "data", "tool", "memory", "agent", "synthesized"):
        return md_type  # type: ignore[return-value]
    if at in ("rag", "document_retrieval"):
        return "rag"
    if at in ("web", "web_intelligence", "web_search"):
        return "web"
    if at in ("data", "data_query") or at.startswith("data_"):
        return "data"
    if at == "tool":
        return "tool"
    if at == "memory" or metadata.get("memory_id"):
        return "memory"
    return "agent"


def normalize_evidence(
    item: Any,
    *,
    goal_id: str = "",
    capability_type: str = "",
    trace_id: str = "",
) -> UnifiedEvidence:
    """Normalize Evidence, dict legacy evidence, or AgentResult-like payloads."""
    if isinstance(item, UnifiedEvidence):
        if goal_id and not item.goal_id:
            return item.model_copy(update={"goal_id": goal_id})
        return item

    if isinstance(item, Evidence):
        md = dict(item.metadata or {})
        prov = item.provenance
        return UnifiedEvidence(
            evidence_id=item.evidence_id,
            source_type=_infer_source_kind(prov.source if prov else "", md),
            source_id=(prov.source if prov else "") or str(md.get("agent_type", "")),
            confidence=float(item.credibility_score or 0.0),
            relevance=float(item.relevance_score or 0.0),
            provenance=prov.model_dump(mode="json") if prov else {},
            citations=list(item.citations or []),
            claims=[str(c) for c in (md.get("claims") or []) if c],
            supporting_data=dict(md.get("supporting_data") or md.get("payload") or {}),
            contradiction_links=[str(x) for x in (md.get("contradiction_links") or [])],
            content=item.content or "",
            content_type=item.content_type or "text",
            goal_id=goal_id or str(md.get("goal_id", "")),
            capability_type=capability_type or str(md.get("capability_type", "")),
            trace_id=trace_id,
            metadata=md,
        )

    if isinstance(item, dict):
        payload = item.get("payload")
        supporting = item.get("supporting_data") or (payload if isinstance(payload, dict) else {})
        if payload is not None and not isinstance(supporting, dict):
            supporting = {"payload": payload}
        agent_type = str(item.get("agent_type") or item.get("source") or "")
        return UnifiedEvidence(
            evidence_id=str(item.get("evidence_id") or uuid.uuid4()),
            source_type=_infer_source_kind(agent_type, item),
            source_id=str(item.get("source") or agent_type),
            confidence=float(item.get("credibility_score") or item.get("confidence") or 0.0),
            relevance=float(item.get("relevance_score") or item.get("relevance") or 0.0),
            provenance=dict(item.get("provenance") or {}),
            citations=list(item.get("citations") or []),
            claims=[str(c) for c in (item.get("claims") or []) if c],
            supporting_data=dict(supporting or {}),
            contradiction_links=[str(x) for x in (item.get("contradiction_links") or [])],
            content=str(item.get("content") or item.get("text") or ""),
            content_type=str(item.get("content_type") or "text"),
            goal_id=goal_id or str(item.get("goal_id", "")),
            capability_type=capability_type or str(item.get("capability_type", "")),
            trace_id=trace_id,
            metadata={k: v for k, v in item.items() if k not in ("content", "payload")},
        )

    # AgentResult or similar object
    agent_type = str(getattr(item, "agent_type", "") or "")
    md = dict(getattr(item, "metadata", None) or {})
    status = str(getattr(item, "status", "success")).lower()
    conf = float(getattr(item, "confidence", 0.0) or 0.0)
    if status not in ("success", "ok", "done"):
        conf = 0.0
    evs = getattr(item, "evidence_objects", None) or []
    if evs:
        first = normalize_evidence(evs[0], goal_id=goal_id, capability_type=capability_type, trace_id=trace_id)
        merged_claims = list(first.claims)
        for extra in evs[1:]:
            u = normalize_evidence(extra, goal_id=goal_id, capability_type=capability_type, trace_id=trace_id)
            merged_claims.extend(u.claims)
        return first.model_copy(
            update={
                "claims": merged_claims,
                "metadata": {**first.metadata, "aggregated_evidence_count": len(evs)},
            }
        )
    legacy = getattr(item, "evidence", None) or []
    citations: list[dict[str, Any]] = []
    supporting: dict[str, Any] = {}
    for leg in legacy:
        if isinstance(leg, dict):
            citations.extend(list(leg.get("citations") or []))
            if leg.get("payload") is not None:
                supporting.setdefault("fragments", []).append(leg.get("payload"))
    return UnifiedEvidence(
        source_type=_infer_source_kind(agent_type, md),
        source_id=agent_type,
        confidence=conf,
        relevance=0.5,
        provenance={"source": agent_type, "source_type": "agent", "confidence": conf},
        citations=citations,
        claims=[str(getattr(item, "content", ""))[:500]] if getattr(item, "content", "") else [],
        supporting_data=supporting,
        content=str(getattr(item, "content", "") or ""),
        goal_id=goal_id,
        capability_type=capability_type or agent_type,
        trace_id=trace_id,
        metadata={**md, "task_id": getattr(item, "task_id", ""), "status": status},
    )


def normalize_evidence_list(
    items: list[Any],
    *,
    goal_id: str = "",
    capability_type: str = "",
    trace_id: str = "",
) -> list[UnifiedEvidence]:
    out: list[UnifiedEvidence] = []
    for item in items or []:
        out.append(
            normalize_evidence(
                item,
                goal_id=goal_id,
                capability_type=capability_type,
                trace_id=trace_id,
            )
        )
    return out


async def publish_unified_to_bus(
    bus: Any,
    items: list[Any],
    *,
    goal_id: str = "",
    capability_type: str = "",
    trace_id: str = "",
) -> list[UnifiedEvidence]:
    """Publish normalized evidence to EvidenceBus (validates lifecycle when possible)."""
    unified = normalize_evidence_list(
        items, goal_id=goal_id, capability_type=capability_type, trace_id=trace_id
    )
    for u in unified:
        ev = u.to_runtime_evidence()
        if hasattr(bus, "publish"):
            await bus.publish(ev)
    return unified