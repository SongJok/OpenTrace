"""
Early turn bootstrap — multi-turn, world hydrate, intent_lock.

Shared by CognitiveKernel and Gateway (KernelRequest metadata) so tier0/resume
paths see the same intent metadata as full kernel runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infra.observability.logger import get_logger
from kernel.cognitive_controls import IntentLock, classify_intent

logger = get_logger(__name__)


@dataclass
class TurnBootstrapResult:
    effective_query: str
    intent_lock: IntentLock
    world_hydrate: dict[str, Any] | None = None
    multi_turn_applied: bool = False


async def bootstrap_turn_intent(
    request: Any,
    *,
    apply_multi_turn: bool = True,
    apply_world_hydrate: bool = True,
) -> TurnBootstrapResult:
    """Resolve query, hydrate world, classify intent; mutates request.metadata."""
    md = dict(getattr(request, "metadata", None) or {})
    # Gateway and kernel share one immutable TurnDecision.  Once present, do
    # not rerun multi-turn/world hydration or any semantic classifier in a
    # downstream entry point; reconstruct the lock below and reuse it.
    decision_reuse = bool(md.get("turn_decision") and md.get("intent_lock"))
    if decision_reuse:
        apply_multi_turn = False
        apply_world_hydrate = False
    force_mode = md.get("force_mode") or getattr(request, "force_mode", None)
    conv_state = getattr(request, "conversation_state", None)
    original_query = (getattr(request, "query", "") or "").strip()
    effective_query = original_query
    multi_applied = False

    if apply_multi_turn and not md.get("multi_turn_resolution"):
        try:
            from kernel.turn_enrichment import apply_multi_turn_resolution

            mtr = await apply_multi_turn_resolution(request, mutate_request=True)
            effective_query = (mtr.query or original_query).strip()
            multi_applied = mtr.multi_turn_applied
            md = dict(getattr(request, "metadata", None) or {})
        except Exception as exc:
            logger.debug("turn_bootstrap_multi_turn_skipped", error=str(exc))
    elif md.get("multi_turn_resolution"):
        effective_query = (getattr(request, "query", "") or original_query).strip()

    world_hydrate: dict[str, Any] | None = None
    if apply_world_hydrate and not md.get("world_hydrate"):
        sid = str(getattr(request, "session_id", "") or "")
        try:
            from kernel.world_turn_begin import hydrate_world_model_for_turn

            wh = await hydrate_world_model_for_turn(session_id=sid, metadata=md)
            if wh.get("hydrated"):
                world_hydrate = wh
                md["world_hydrate"] = wh
                if wh.get("cross_process_slices"):
                    md["world_cross_process"] = wh["cross_process_slices"]
        except Exception as exc:
            logger.debug("turn_bootstrap_world_skipped", error=str(exc))

    if not md.get("intent_lock"):
        intent_lock = classify_intent(
            effective_query,
            force_mode,
            prior_intent=getattr(conv_state, "active_intent", None) if conv_state else None,
            prior_domain=getattr(conv_state, "active_domain", None) if conv_state else None,
            conversation_phase=getattr(conv_state, "conversation_phase", None) if conv_state else None,
        )
        md["intent_lock"] = intent_lock.to_dict()
        md["raw_user_query"] = intent_lock.raw_user_query
        md["protected_intent"] = intent_lock.protected_intent
        md["task_type"] = intent_lock.task_type
        md["relevance_threshold"] = intent_lock.relevance_threshold
        if conv_state is not None:
            conv_state.active_intent = intent_lock.task_type
            conv_state.active_domain = intent_lock.task_type
    else:
        lock_d = md["intent_lock"]
        from kernel.cognitive_controls import CognitiveBudget

        budget_raw = lock_d.get("cognitive_budget") or {}
        budget = CognitiveBudget()
        if isinstance(budget_raw, dict):
            budget = CognitiveBudget(
                **{k: budget_raw[k] for k in budget_raw if k in CognitiveBudget.__dataclass_fields__}
            )
        intent_lock = IntentLock(
            raw_user_query=str(lock_d.get("raw_user_query") or effective_query),
            normalized_query=str(lock_d.get("normalized_query") or effective_query),
            protected_intent=str(lock_d.get("protected_intent") or effective_query),
            task_type=str(lock_d.get("task_type") or "general_qa"),
            complexity_level=str(lock_d.get("complexity_level") or "L2"),
            allowed_capabilities=list(lock_d.get("allowed_capabilities") or []),
            disallowed_capabilities=list(lock_d.get("disallowed_capabilities") or []),
            confidence=float(lock_d.get("confidence") or 0.9),
            cognitive_budget=budget,
            relevance_threshold=float(lock_d.get("relevance_threshold") or 0.35),
        )

    if hasattr(request, "metadata"):
        # A single immutable routing decision is shared by gateway, kernel and
        # runtime.  Downstream stages may enrich it but must not reclassify the
        # user turn.
        md["turn_decision"] = {
            "task_type": intent_lock.task_type,
            "normalized_query": intent_lock.normalized_query,
            "allowed_capabilities": list(intent_lock.allowed_capabilities),
            "disallowed_capabilities": list(intent_lock.disallowed_capabilities),
            "confidence": intent_lock.confidence,
            "relevance_threshold": intent_lock.relevance_threshold,
            "cognitive_budget": intent_lock.to_dict().get("cognitive_budget", {}),
            "force_mode": force_mode,
        }
        request.metadata = md
    if multi_applied and effective_query != original_query:
        request.query = effective_query

    return TurnBootstrapResult(
        effective_query=effective_query,
        intent_lock=intent_lock,
        world_hydrate=world_hydrate,
        multi_turn_applied=multi_applied,
    )
