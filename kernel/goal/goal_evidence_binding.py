"""将证据和制品绑定到 GoalGraph（合约级 ID）。"""

from __future__ import annotations

from typing import Any


def extract_evidence_ids(evidence_objects: list[Any]) -> list[str]:
    ids: list[str] = []
    for i, ev in enumerate(evidence_objects or []):
        eid = getattr(ev, "evidence_id", None) or getattr(ev, "id", None)
        if eid:
            ids.append(str(eid))
        else:
            ids.append(f"ev:{i}")
    return ids


def stamp_evidence_goal_ids(
    evidence_objects: list[Any],
    *,
    root_goal_id: str,
    request_id: str = "",
) -> None:
    """将 goal_id 附加到证据元数据，供融合/回放使用。"""
    for ev in evidence_objects or []:
        md = getattr(ev, "metadata", None)
        if md is None:
            try:
                ev.metadata = {}
                md = ev.metadata
            except Exception:
                continue
        if isinstance(md, dict):
            md.setdefault("goal_id", root_goal_id)
            md.setdefault("request_id", request_id)


def build_goal_evidence_binding(
    *,
    root_goal_id: str,
    artifact_id: str,
    evidence_ids: list[str],
    session_id: str = "",
) -> Any:
    from kernel.protocol.runtime_contract import GoalEvidenceBinding

    return GoalEvidenceBinding(
        root_goal_id=root_goal_id,
        artifact_id=artifact_id,
        evidence_ids=list(evidence_ids),
        session_id=session_id,
    )


def merge_binding_into_artifact_trace(
    artifact: Any,
    binding: Any,
) -> None:
    if hasattr(artifact, "goal_evidence_binding"):
        artifact.goal_evidence_binding = binding
    if not hasattr(artifact, "execution_trace"):
        return
    trace = artifact.execution_trace
    if trace.metadata is None:
        trace.metadata = {}
    if hasattr(binding, "__dataclass_fields__"):
        from dataclasses import asdict

        trace.metadata["goal_evidence_binding"] = asdict(binding)
    else:
        trace.metadata["goal_evidence_binding"] = binding