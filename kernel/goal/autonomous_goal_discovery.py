"""P2 — Propose goals from anomalies / evidence (deterministic stub)."""

from __future__ import annotations

from typing import Any


def propose_goals_from_signals(
    *,
    query: str,
    claim_graph: dict[str, Any] | None = None,
    anomaly_hints: list[str] | None = None,
    root_id: str = "proposed_root",
) -> list[dict[str, Any]]:
    """Return proposed sub-goal specs (not yet committed to GoalGraph)."""
    proposals: list[dict[str, Any]] = []
    cg = claim_graph or {}
    if int(cg.get("conflicting_claims", 0) or 0) > 0:
        proposals.append(
            {
                "goal_id": f"{root_id}:resolve_conflicts",
                "description": "澄清并化解证据冲突",
                "domain": "risk",
                "source": "autonomous_goal_discovery",
            }
        )
    for hint in anomaly_hints or []:
        if "multi_kpi" in hint:
            proposals.append(
                {
                    "goal_id": f"{root_id}:clarify_kpi",
                    "description": "澄清 KPI 口径与时间粒度",
                    "domain": "analytics",
                    "source": "autonomous_goal_discovery",
                }
            )
    if not proposals and "风险" in (query or ""):
        proposals.append(
            {
                "goal_id": f"{root_id}:risk_review",
                "description": "风险复核",
                "domain": "risk",
                "source": "autonomous_goal_discovery",
            }
        )
    return proposals


def attach_proposals_to_metadata(metadata: dict[str, Any], proposals: list[dict[str, Any]]) -> None:
    if not proposals:
        return
    metadata["autonomous_goal_proposals"] = proposals


def maybe_mount_proposals_on_goal_graph(
    metadata: dict[str, Any],
    *,
    max_mount: int = 2,
) -> dict[str, Any]:
    """Optionally merge proposals into goal_graph when commit flag is on (advisory sub-goals)."""
    out: dict[str, Any] = {"mounted": [], "skipped": False}
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_autonomous_goal_commit_enabled", False)):
            out["skipped"] = "commit_disabled"
            return out
    except Exception:
        out["skipped"] = "settings"
        return out

    proposals = metadata.get("autonomous_goal_proposals") or []
    if not isinstance(proposals, list) or not proposals:
        return out

    gg = metadata.get("goal_graph")
    if not isinstance(gg, dict):
        return out

    goals = list(gg.get("goals") or [])
    root_id = str(gg.get("root_goal_id", "") or "")
    existing_ids = {str(g.get("goal_id", "")) for g in goals if isinstance(g, dict)}

    for spec in proposals[:max_mount]:
        if not isinstance(spec, dict):
            continue
        gid = str(spec.get("goal_id", "") or "")
        if not gid or gid in existing_ids:
            continue
        goals.append(
            {
                "goal_id": gid,
                "description": str(spec.get("description", "") or gid),
                "priority": 0,
                "parent_id": root_id or None,
                "success_criteria": "",
                "metadata": {
                    "source": "autonomous_goal_discovery",
                    "domain": spec.get("domain", ""),
                    "advisory": True,
                },
            }
        )
        existing_ids.add(gid)
        out["mounted"].append(gid)

    if out["mounted"]:
        gg["goals"] = goals
        metadata["goal_graph"] = gg
        metadata["autonomous_goal_mounted"] = list(out["mounted"])
    return out