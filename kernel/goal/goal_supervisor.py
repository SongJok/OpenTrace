"""
Goal Intelligence — split, merge, conflict resolution, retirement hints.

Invoked from CognitiveSupervisor before GoalGraph is bound to context.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from kernel.protocol.runtime_contract import Goal, GoalGraph


@dataclass
class GoalSupervisorDecision:
    graph: GoalGraph
    merged_goal_ids: list[str] = field(default_factory=list)
    split_from_root: bool = False
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    retired_goal_ids: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "goal_supervisor": {
                "merged_goal_ids": list(self.merged_goal_ids),
                "split_from_root": self.split_from_root,
                "conflicts": list(self.conflicts),
                "retired_goal_ids": list(self.retired_goal_ids),
                "domains": list(self.domains),
                "goal_count": len(self.graph.goals),
            }
        }


_BUSINESS_OVERVIEW_PATTERNS = (
    r"业务情况",
    r"整体情况",
    r"本季度",
    r"本月",
    r"经营状况",
    r"怎么样",
    r"概况",
    r"overview",
    r"business\s+performance",
)

_AXIS_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    ("revenue", "收入与增长", "revenue"),
    ("cost", "成本与费用", "cost"),
    ("risk", "风险与合规", "risk"),
    ("growth", "增长与转化", "growth"),
)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _fingerprint(description: str) -> str:
    norm = _normalize_text(description)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _is_business_overview_query(query: str, task_type: str) -> bool:
    q = _normalize_text(query)
    if task_type in ("data_query", "analytics", "business_review"):
        if any(re.search(p, q, re.I) for p in _BUSINESS_OVERVIEW_PATTERNS):
            return True
    return any(re.search(p, q, re.I) for p in _BUSINESS_OVERVIEW_PATTERNS[:6])


def _merge_duplicate_subgoals(graph: GoalGraph, root_id: str) -> tuple[GoalGraph, list[str]]:
    merged: list[str] = []
    seen: dict[str, str] = {}
    kept: list[Goal] = []
    for g in graph.goals:
        if g.goal_id == root_id:
            kept.append(g)
            continue
        fp = _fingerprint(g.description)
        if fp in seen:
            merged.append(g.goal_id)
            continue
        seen[fp] = g.goal_id
        kept.append(g)
    graph.goals = kept
    return graph, merged


def _split_root_into_axes(graph: GoalGraph, root_id: str, query: str) -> tuple[GoalGraph, bool, list[str]]:
    domains: list[str] = []
    root = next((g for g in graph.goals if g.goal_id == root_id), None)
    if root is None:
        return graph, False, domains
    subs = [g for g in graph.goals if g.parent_id == root_id]
    if subs:
        domains = [
            str((g.metadata or {}).get("domain") or (g.metadata or {}).get("axis") or "")
            for g in subs
            if (g.metadata or {}).get("domain") or (g.metadata or {}).get("axis")
        ]
        return graph, False, [d for d in domains if d]

    if not _is_business_overview_query(query, graph.intent_category):
        return graph, False, domains

    for i, (axis, label, domain) in enumerate(_AXIS_TEMPLATES):
        gid = f"{root_id}:axis:{axis}"
        graph.add_goal(
            Goal(
                goal_id=gid,
                description=f"{label}（{query.strip()[:80]}）",
                parent_id=root_id,
                priority=i,
                metadata={"domain": domain, "axis": axis, "role": "sub_goal", "source": "goal_supervisor"},
            )
        )
        domains.append(domain)
    root.metadata = dict(root.metadata or {})
    root.metadata["role"] = "root"
    root.metadata["decomposed_by"] = "goal_supervisor"
    return graph, True, domains


def _detect_conflicts(graph: GoalGraph, root_id: str) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    subs = [g for g in graph.goals if g.parent_id == root_id]
    domains = [str((g.metadata or {}).get("domain", "")) for g in subs]
    if "revenue" in domains and "cost" in domains:
        conflicts.append(
            {
                "type": "tradeoff",
                "message": "revenue_and_cost_goals_may_compete_for_attention",
                "goal_ids": [g.goal_id for g in subs],
            }
        )
    priorities = [g.priority for g in subs]
    if subs and len(set(priorities)) < len(priorities):
        conflicts.append(
            {
                "type": "priority_collision",
                "message": "duplicate_sub_goal_priorities",
                "goal_ids": [g.goal_id for g in subs],
            }
        )
    return conflicts


def _apply_retirement_hints(graph: GoalGraph, request_metadata: dict[str, Any]) -> tuple[GoalGraph, list[str]]:
    retired: list[str] = []
    archive = request_metadata.get("goal_archive") or request_metadata.get("retired_goals") or []
    if not isinstance(archive, list):
        return graph, retired
    archive_set = {str(x) for x in archive}
    kept: list[Goal] = []
    for g in graph.goals:
        if g.goal_id in archive_set:
            retired.append(g.goal_id)
            continue
        kept.append(g)
    graph.goals = kept
    return graph, retired


def enrich_goal_graph_from_request(
    graph: GoalGraph,
    *,
    query: str,
    request_metadata: dict[str, Any] | None = None,
) -> GoalSupervisorDecision:
    """Apply goal intelligence transforms to a GoalGraph (pure, testable)."""
    md = dict(request_metadata or {})
    root_id = graph.root_goal_id
    graph, retired = _apply_retirement_hints(graph, md)
    graph, merged = _merge_duplicate_subgoals(graph, root_id)
    graph, split, domains = _split_root_into_axes(graph, root_id, query)
    conflicts = _detect_conflicts(graph, root_id)
    if conflicts:
        subs = [g for g in graph.goals if g.parent_id == root_id]
        for i, g in enumerate(sorted(subs, key=lambda x: x.priority)):
            g.priority = i
    return GoalSupervisorDecision(
        graph=graph,
        merged_goal_ids=merged,
        split_from_root=split,
        conflicts=conflicts,
        retired_goal_ids=retired,
        domains=domains,
    )


def apply_goal_supervisor_to_request(request: Any, graph: GoalGraph) -> GoalSupervisorDecision:
    """Entry when kernel_goal_supervisor_enabled is on."""
    from infra.config.settings import settings

    if not bool(getattr(settings, "kernel_goal_supervisor_enabled", True)):
        return GoalSupervisorDecision(graph=graph)
    decision = enrich_goal_graph_from_request(
        graph,
        query=str(getattr(request, "query", "") or ""),
        request_metadata=dict(getattr(request, "metadata", None) or {}),
    )
    request.metadata = dict(getattr(request, "metadata", None) or {})
    request.metadata.update(decision.to_metadata())
    request.metadata["goal_graph"] = decision.graph.to_dict()
    subs = request.metadata.get("decomposed_goals") or request.metadata.get("sub_questions")
    if decision.split_from_root and not subs:
        request.metadata["decomposed_goals"] = [
            {"text": g.description, "domain": (g.metadata or {}).get("domain", "")}
            for g in decision.graph.goals
            if g.parent_id == decision.graph.root_goal_id
        ]
    return decision