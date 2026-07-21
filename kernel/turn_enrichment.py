"""
Unified turn enrichment — multi-turn, preference, memory, context fabric.

Kernel.run/stream and CognitiveSupervisor.prepare_run share this module so
vNext gateway paths get the same cognitive context as the full kernel path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TurnEnrichmentResult:
    """Mutable turn fields after enrichment."""

    query: str
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    memory_context: list[dict[str, Any]] = field(default_factory=list)
    memory_injection_query: str = ""
    conversation_summary: str = ""
    assembled_context: dict[str, Any] | None = None
    multi_turn_applied: bool = False


def _intent_lock_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    lock = metadata.get("intent_lock")
    return lock if isinstance(lock, dict) and lock else None


def _memory_budget_allowed(lock: dict[str, Any] | None) -> bool:
    if not lock:
        return True
    budget = lock.get("cognitive_budget")
    if isinstance(budget, dict):
        return bool(budget.get("memory_injection", True))
    return True


def personalization_memory_enabled(metadata: dict[str, Any] | None) -> bool:
    """Whether a turn may read or write cross-turn personalization memory.

    ``temporary`` intentionally keeps the current request and its explicit
    conversation history, but must not retrieve or update saved preferences,
    semantic memory, episodic memory, or history indexes.
    """
    mode = str((metadata or {}).get("memory_mode") or "enabled").strip().lower()
    return mode == "enabled"


def inject_multi_turn_constraints_into_metadata(
    metadata: dict[str, Any],
    mtr: Any,
) -> None:
    """Flatten reference_resolution constraints for Data/RAG agent params (P0)."""
    if not isinstance(metadata, dict):
        return
    merged: dict[str, Any] = {}
    ref = getattr(mtr, "reference_result", None)
    if ref is not None:
        cc = getattr(ref, "corrected_constraints", None) or {}
        if isinstance(cc, dict) and cc:
            merged.update(cc)
    mtr_md = mtr.to_metadata() if hasattr(mtr, "to_metadata") else {}
    rr = mtr_md.get("reference_resolution") if isinstance(mtr_md, dict) else {}
    if isinstance(rr, dict):
        cc2 = rr.get("corrected_constraints") or {}
        if isinstance(cc2, dict):
            merged.update(cc2)
        if rr.get("suggested_domain"):
            merged.setdefault("suggested_domain", rr["suggested_domain"])
        if rr.get("suggested_agent"):
            merged.setdefault("suggested_agent", rr["suggested_agent"])
    if merged:
        metadata["multi_turn_constraints"] = merged


async def apply_multi_turn_resolution(
    request: Any,
    *,
    mutate_request: bool = True,
) -> TurnEnrichmentResult:
    """DST + reference resolver; optionally mutates request.query and metadata."""
    md = dict(getattr(request, "metadata", None) or {})
    original_query = (getattr(request, "query", "") or "").strip()
    force_mode = md.get("force_mode") or getattr(request, "force_mode", None)
    conv_state = getattr(request, "conversation_state", None)
    history = (
        getattr(request, "history", None)
        or md.get("history")
        or []
    )

    from kernel.multi_turn_resolution import resolve_multi_turn_query

    mtr = await resolve_multi_turn_query(
        original_query,
        conversation_state=conv_state,
        history=history,
        force_mode=force_mode,
    )
    effective = (mtr.resolved_query or original_query).strip()
    applied = bool(mtr.applied)

    # 每轮保留用户原文，供 RAG/记忆检索与展示（勿与 history 最后一条 user 混淆）
    md.setdefault("raw_user_query", original_query)

    if applied:
        md["multi_turn_resolution"] = mtr.to_metadata()
        inject_multi_turn_constraints_into_metadata(md, mtr)
        if conv_state is not None and mtr.dialogue_state is not None:
            if getattr(mtr.dialogue_state, "turn_type", "") == "follow_up":
                conv_state.conversation_phase = "follow_up"
        if mutate_request:
            request.query = effective
            request.metadata = md

    return TurnEnrichmentResult(
        query=effective,
        metadata=md,
        history=list(history) if isinstance(history, list) else [],
        multi_turn_applied=applied,
    )


async def apply_preference_and_memory(
    request: Any,
    *,
    base: TurnEnrichmentResult | None = None,
) -> TurnEnrichmentResult:
    """Preference injection + memory fabric retrieval into metadata."""
    from infra.config.settings import settings

    sid = str(getattr(request, "session_id", "") or "")
    user_id = str(getattr(request, "user_id", "") or "")
    conv_state = getattr(request, "conversation_state", None)
    md = dict(base.metadata if base else (getattr(request, "metadata", None) or {}))
    query = (base.query if base else getattr(request, "query", "")) or ""

    if not personalization_memory_enabled(md):
        custom = str(md.get("custom_instruction_block") or "").strip()
        md.pop("user_preference_context_block", None)
        md.pop("user_preferences", None)
        md.pop("preference_layers", None)
        if custom:
            md["user_preference_context_block"] = f"## 用户明确指令\n{custom[:8000]}"
        md["memory_context"] = []
        md["memory_status"] = "disabled"
        if hasattr(request, "metadata"):
            request.metadata = md
        out = base or TurnEnrichmentResult(query=query, metadata=md)
        out.metadata = md
        out.memory_context = []
        return out

    try:
        from kernel.preference_injection import apply_preference_injection_for_turn

        md = await apply_preference_injection_for_turn(
            user_id=user_id,
            session_id=sid,
            metadata=md,
            conversation_state=conv_state,
        )
    except Exception as exc:
        logger.debug("turn_enrichment_preference_skipped", error=str(exc))

    memory_context: list[dict[str, Any]] = []
    lock = _intent_lock_from_metadata(md)
    budget_allows = _memory_budget_allowed(lock)

    if settings.kernel_memory_context_enabled and sid:
        try:
            from kernel.memory_injection import inject_memory_context_for_turn

            memory_context = await inject_memory_context_for_turn(
                session_id=sid,
                query=query,
                metadata=md,
                memory_injection_enabled=True,
                budget_allows_memory=budget_allows,
                top_k=8,
            )
            md["memory_context"] = memory_context
        except Exception as exc:
            logger.debug("turn_enrichment_memory_skipped", error=str(exc))

    if hasattr(request, "metadata"):
        request.metadata = md

    out = base or TurnEnrichmentResult(query=query, metadata=md)
    out.metadata = md
    out.memory_context = memory_context
    return out


async def apply_context_fabric_assembly(
    request: Any,
    *,
    base: TurnEnrichmentResult | None = None,
) -> TurnEnrichmentResult:
    """Assemble summary/memory/attachment blocks via ContextFabric."""
    from kernel.turn_context import TurnContext

    md = dict(base.metadata if base else (getattr(request, "metadata", None) or {}))
    query = (base.query if base else getattr(request, "query", "")) or ""
    sid = str(getattr(request, "session_id", "") or "")
    history = (
        base.history
        if base and base.history
        else list(getattr(request, "history", None) or md.get("history") or [])
    )

    assembled_ctx = None
    try:
        from kernel.context_fabric import get_context_fabric

        tctx = TurnContext(
            session_id=sid,
            user_id=str(getattr(request, "user_id", "") or ""),
            query=query,
            recent_history=history,
            memory_context=base.memory_context if base else md.get("memory_context"),
            attachment_contexts=md.get("attachment_contexts"),
            metadata=md,
            conversation_state=getattr(request, "conversation_state", None),
        )
        assembled_ctx = await get_context_fabric().assemble(tctx)
    except Exception as exc:
        logger.warning("turn_enrichment_fabric_skipped", error=str(exc))

    effective_history = (
        assembled_ctx.recent_turns
        if (assembled_ctx and assembled_ctx.compressed)
        else history
    )
    memory_injection_query = (
        assembled_ctx.memory_injection_query if assembled_ctx else query
    )
    conversation_summary = assembled_ctx.summary_block if assembled_ctx else ""

    assembled_dict: dict[str, Any] | None = None
    if assembled_ctx:
        assembled_dict = {
            "summary_block": assembled_ctx.summary_block,
            "memory_block": assembled_ctx.memory_block,
            "attachment_block": assembled_ctx.attachment_block,
            "state_block": assembled_ctx.state_block,
            "total_tokens": assembled_ctx.total_tokens,
            "compressed": assembled_ctx.compressed,
            "metadata": dict(assembled_ctx.metadata or {}),
        }
        md["assembled_context"] = assembled_dict
        md["memory_injection_query"] = memory_injection_query
        md["conversation_summary"] = conversation_summary
        if assembled_ctx.metadata.get("fabric_graph"):
            md.setdefault("fabric_graph", assembled_ctx.metadata["fabric_graph"])

    if hasattr(request, "metadata"):
        request.metadata = md
    if assembled_ctx and effective_history is not history:
        if hasattr(request, "history"):
            request.history = effective_history

    out = base or TurnEnrichmentResult(query=query, metadata=md, history=list(history))
    out.metadata = md
    out.history = list(effective_history)
    out.memory_injection_query = memory_injection_query
    out.conversation_summary = conversation_summary
    out.assembled_context = assembled_dict
    if base:
        out.memory_context = base.memory_context
        out.multi_turn_applied = base.multi_turn_applied
    return out


async def enrich_turn_before_dispatch(
    request: Any,
    *,
    skip_multi_turn: bool = False,
    skip_memory: bool = False,
    skip_fabric: bool = False,
) -> TurnEnrichmentResult:
    """
    Full P0 enrichment chain for Supervisor / Kernel gateway handoff.

    Does not run intent_lock or world_hydrate (remain in CognitiveKernel).
    """
    base: TurnEnrichmentResult | None = None
    if not skip_multi_turn:
        base = await apply_multi_turn_resolution(request, mutate_request=True)
    if not skip_memory:
        base = await apply_preference_and_memory(request, base=base)
    if not skip_fabric:
        base = await apply_context_fabric_assembly(request, base=base)
    if base is None:
        md = dict(getattr(request, "metadata", None) or {})
        base = TurnEnrichmentResult(
            query=str(getattr(request, "query", "") or ""),
            metadata=md,
            history=list(getattr(request, "history", None) or []),
        )
    md = dict(base.metadata or getattr(request, "metadata", None) or {})
    md["turn_enrichment_applied"] = True
    if base.memory_injection_query:
        md["memory_injection_query"] = base.memory_injection_query
    if base.conversation_summary:
        md["conversation_summary"] = base.conversation_summary
    if base.assembled_context:
        md["assembled_context"] = base.assembled_context
    if hasattr(request, "metadata"):
        request.metadata = md
    base.metadata = md
    return base


def sync_enrichment_metadata_to_runtime_context(ctx: Any, request: Any) -> None:
    """Mirror request.metadata enrichment fields onto RuntimeContext after prepare_run."""
    if ctx is None:
        return
    md = dict(getattr(request, "metadata", None) or {})
    ctx.metadata = {**(getattr(ctx, "metadata", None) or {}), **md}
    if getattr(request, "query", None):
        ctx.query = str(request.query)
    mem = md.get("memory_context")
    if mem and not getattr(ctx, "memory_context", None):
        if isinstance(mem, list):
            ctx.memory_context = "\n".join(
                str(m.get("content", ""))[:800]
                for m in mem[:8]
                if isinstance(m, dict)
            )
        else:
            ctx.memory_context = str(mem)
    pref = md.get("user_preference_context_block")
    if pref:
        ctx.preference_context_block = str(pref)
    assembled = md.get("assembled_context")
    if assembled and isinstance(assembled, dict):
        summary = assembled.get("summary_block") or md.get("conversation_summary")
        if summary and hasattr(ctx, "conversation_summary"):
            ctx.conversation_summary = str(summary)


def attach_enrichment_to_runtime_context(ctx: Any, enriched: TurnEnrichmentResult) -> None:
    """Copy enrichment fields onto RuntimeContext for executives and agents."""
    if ctx is None:
        return
    ctx.query = enriched.query
    ctx.metadata = dict(enriched.metadata or {})
    if enriched.history:
        ctx.conversation_history = enriched.history
    if enriched.memory_context and not getattr(ctx, "memory_context", None):
        ctx.memory_context = "\n".join(
            str(m.get("content", ""))[:800]
            for m in enriched.memory_context[:8]
            if isinstance(m, dict)
        )
    block = enriched.conversation_summary or ""
    pref = str(ctx.metadata.get("user_preference_context_block", "") or "")
    if pref and block:
        ctx.preference_context_block = pref
    elif pref:
        ctx.preference_context_block = pref


def runtime_agent_params_from_context(ctx: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Standard params bag for TaskMessage from RuntimeContext."""
    md = dict(getattr(ctx, "metadata", None) or {})
    params: dict[str, Any] = {
        "session_id": getattr(ctx, "session_id", ""),
        "user_id": getattr(ctx, "user_id", ""),
        "memory_injection_query": md.get("memory_injection_query") or getattr(ctx, "query", ""),
        "conversation_summary": md.get("conversation_summary", ""),
        "assembled_context": md.get("assembled_context"),
        "multi_turn_resolution": md.get("multi_turn_resolution"),
        "multi_turn_constraints": md.get("multi_turn_constraints"),
        "user_preference_context_block": md.get("user_preference_context_block", ""),
        "relevance_threshold": md.get("relevance_threshold")
        or getattr(ctx, "relevance_threshold", 0.35),
        "data_source_context": getattr(ctx, "data_source_context", None) or md.get("data_source_context"),
        "goal_graph": md.get("goal_graph"),
        "world_hydrate": md.get("world_hydrate"),
        "memory_context": md.get("memory_context"),
        "tenant_id": md.get("tenant_id"),
        "workspace_id": md.get("workspace_id"),
    }
    if extra:
        params.update(extra)
    return params
