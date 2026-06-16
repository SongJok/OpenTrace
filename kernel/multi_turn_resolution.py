"""多轮 query 解析门面 — DST + ReferenceResolver，供 vNext 主路径复用。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kernel.dialogue_state_tracker import DialogueStateTracker
from kernel.reference_resolver import ReferenceResolver, ReferenceResult


@dataclass
class MultiTurnResolution:
    original_query: str
    resolved_query: str
    dialogue_state: Any = None
    reference_result: ReferenceResult | None = None
    applied: bool = False

    def to_metadata(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "original_query": self.original_query,
            "resolved_query": self.resolved_query,
            "applied": self.applied,
        }
        if self.dialogue_state is not None:
            out["dialogue_state"] = {
                "active_domain": getattr(self.dialogue_state, "active_domain", ""),
                "referenced_previous_result": getattr(
                    self.dialogue_state, "referenced_previous_result", False
                ),
                "referenced_agent_type": getattr(self.dialogue_state, "referenced_agent_type", ""),
                "resolved_query": getattr(self.dialogue_state, "resolved_query", ""),
                "turn_type": getattr(self.dialogue_state, "turn_type", ""),
            }
        if self.reference_result is not None and self.reference_result.confidence >= 0.5:
            out["reference_resolution"] = {
                "turn_type": self.reference_result.turn_type,
                "resolved_query": self.reference_result.resolved_query,
                "confidence": self.reference_result.confidence,
                "corrected_constraints": dict(self.reference_result.corrected_constraints or {}),
                "suggested_domain": self.reference_result.suggested_domain,
                "suggested_agent": self.reference_result.suggested_agent,
            }
        return out


async def resolve_multi_turn_query(
    query: str,
    *,
    conversation_state: Any = None,
    conv_state_dict: dict[str, Any] | None = None,
    history: Any = None,
    result_refs: Any = None,
    force_mode: str | None = None,
) -> MultiTurnResolution:
    """在 intent 分类前展开追问/指代；force_mode 时跳过。"""
    original = (query or "").strip()
    if not original or force_mode:
        return MultiTurnResolution(
            original_query=original,
            resolved_query=original,
            applied=False,
        )

    resolved = original
    dialogue_state = None
    reference_result: ReferenceResult | None = None
    applied = False

    prev_plan = None
    prev_results = None
    if conv_state_dict:
        prev_plan = conv_state_dict.get("last_plan")
        prev_results = conv_state_dict.get("last_results")
    elif conversation_state is not None:
        prev_plan = getattr(conversation_state, "last_plan", None)
        prev_results = getattr(conversation_state, "last_results", None)

    try:
        dst = DialogueStateTracker()
        dialogue_state = await dst.track(
            original,
            previous_plan=prev_plan,
            previous_results=prev_results,
            history=history,
        )
        if dialogue_state.resolved_query and dialogue_state.resolved_query != original:
            resolved = dialogue_state.resolved_query
            applied = True
    except Exception:
        dialogue_state = None

    try:
        resolver = ReferenceResolver()
        refs = result_refs
        if refs is None and conversation_state is not None:
            refs = getattr(conversation_state, "last_result_refs", None)
        reference_result = await resolver.resolve_with_llm(
            original,
            conversation_state,
            result_refs=refs,
        )
        if reference_result.confidence >= 0.5 and reference_result.resolved_query:
            if reference_result.resolved_query != resolved:
                resolved = reference_result.resolved_query
                applied = True
    except Exception:
        reference_result = None

    if conversation_state is not None:
        # Always record the latest user utterance as the active goal (not only turn 1).
        conversation_state.last_user_goal = original
        if reference_result is not None and reference_result.turn_type == "correction":
            conversation_state.last_turn_type = "correction"
            if reference_result.corrected_constraints:
                ac = getattr(conversation_state, "active_constraints", None) or {}
                if isinstance(ac, dict):
                    ac = dict(ac)
                    ac.update(reference_result.corrected_constraints)
                    conversation_state.active_constraints = ac
        if dialogue_state is not None and getattr(dialogue_state, "turn_type", "") == "follow_up":
            conversation_state.conversation_phase = "follow_up"

    return MultiTurnResolution(
        original_query=original,
        resolved_query=resolved,
        dialogue_state=dialogue_state,
        reference_result=reference_result,
        applied=applied,
    )