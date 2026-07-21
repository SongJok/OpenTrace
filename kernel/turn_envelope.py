"""Turn envelope metadata for high-level cognitive flow tracing."""

from __future__ import annotations

from typing import Any

_MODEL_ONLY_CAPABILITIES = {"", "model.answer", "model", "answer"}


def tool_decision_from_intent_lock(lock: Any, *, force_mode: str | None = None) -> dict[str, Any]:
    """Build a stable no-tool/tool decision from IntentLock-like objects."""
    allowed = list(getattr(lock, "allowed_capabilities", None) or [])
    task_type = str(getattr(lock, "task_type", "") or "")
    if force_mode:
        return {
            "need_tool": True,
            "reason": "force_mode",
            "force_mode": force_mode,
            "allowed_capabilities": allowed,
        }
    tool_caps = [cap for cap in allowed if str(cap) not in _MODEL_ONLY_CAPABILITIES]
    if tool_caps:
        return {
            "need_tool": True,
            "reason": "intent_capability",
            "allowed_capabilities": allowed,
        }
    if task_type in {"identity", "greeting", "capability_help", "usage_help"}:
        return {
            "need_tool": False,
            "reason": f"{task_type}_direct",
            "allowed_capabilities": allowed,
        }
    return {
        "need_tool": False,
        "reason": "model_answer_allowed",
        "allowed_capabilities": allowed,
    }


def build_turn_envelope(
    *,
    request: Any,
    intent_lock: Any | None = None,
    route: str,
    path: str,
    mode: str,
    answer_source: str,
    stop_reason: str,
    tool_decision: dict[str, Any] | None = None,
    context_layers: list[str] | None = None,
    memory_status: str = "not_required",
    safety_status: str = "allowed",
    output_guard: str = "normal",
) -> dict[str, Any]:
    """Create the project-level turn flow envelope stored under metadata.turn_envelope."""
    md = dict(getattr(request, "metadata", None) or {})
    query = str(getattr(request, "query", "") or "")
    history = list(getattr(request, "history", None) or [])
    lock_dict = (
        intent_lock.to_dict()
        if hasattr(intent_lock, "to_dict")
        else dict(intent_lock or {})
        if isinstance(intent_lock, dict)
        else {}
    )
    decision = tool_decision or tool_decision_from_intent_lock(intent_lock)
    layers = context_layers or [
        "system_identity",
        "developer_policy",
        "conversation_history" if history else "conversation_history_empty",
        "user_message",
    ]
    if md.get("attachment_contexts"):
        layers.append("attachments")
    if md.get("memory_context"):
        layers.append("memory")
    if md.get("assembled_context") or md.get("composed_context"):
        layers.append("context_fabric")

    return {
        "version": "turn_envelope_v1",
        "input": {
            "query_chars": len(query),
            "history_messages": len(history),
            "has_attachments": bool(md.get("attachment_contexts")),
            "force_mode": md.get("force_mode") or "",
        },
        "context": {
            "layers": layers,
            "memory_status": memory_status,
            "assembled": bool(md.get("assembled_context") or md.get("composed_context")),
        },
        "intent": {
            "task_type": lock_dict.get("task_type", ""),
            "complexity_level": lock_dict.get("complexity_level", ""),
            "confidence": lock_dict.get("confidence", 0.0),
        },
        "tool_planning": decision,
        "safety": {
            "input_policy": safety_status,
            "output_guard": output_guard,
        },
        "execution": {
            "path": path,
            "route": route,
            "answer_source": answer_source,
        },
        "streaming": {
            "mode": mode,
        },
        "finalize": {
            "status": "completed",
            "stop_reason": stop_reason,
        },
    }


def attach_turn_envelope(metadata: dict[str, Any] | None, envelope: dict[str, Any]) -> dict[str, Any]:
    """Return a metadata copy with a normalized turn envelope attached."""
    out = dict(metadata or {})
    out["turn_envelope"] = envelope
    return out
