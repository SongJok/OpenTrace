"""Direct ToolAgent dispatch — Tier-0 tool path with manifest + audit envelope."""

from __future__ import annotations

import time
import uuid
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger
from kernel.agent_runtime.manifest import get_manifest
from kernel.runtime.fast_path_metadata import build_fast_path_governance_envelope

logger = get_logger(__name__)

_TOOL_TASK_TYPES = frozenset({"weather", "time", "tool"})


def should_use_tool_fast_path(
    intent_lock: Any | None,
    *,
    force_mode: str | None = None,
) -> bool:
    if not bool(getattr(settings, "kernel_tool_fast_path_enabled", True)):
        return False
    fm = (force_mode or "").strip().lower()
    if fm == "tool":
        return True
    if not intent_lock:
        return False
    if isinstance(intent_lock, dict):
        tt = str(intent_lock.get("task_type") or "").lower()
    else:
        tt = str(getattr(intent_lock, "task_type", "") or "").lower()
    return tt in _TOOL_TASK_TYPES


def _tool_governance_meta(request: Any, *, task_type: str, tool_name: str | None) -> dict[str, Any]:
    md = dict(request.metadata or {})
    req_id = str(md.get("request_id") or uuid.uuid4())
    cap, reg = get_manifest().resolve_capability_alias("tool")
    meta = build_fast_path_governance_envelope(
        route="tool_fast_path",
        capability_type=cap,
        registry_agent=reg,
        request_id=req_id,
        session_id=str(getattr(request, "session_id", "") or ""),
        tier="tier0",
        extra={
            "tool_fast_path": True,
            "intent_task_type": task_type,
            "tool_name": tool_name,
            "tenant_id": str(md.get("tenant_id") or "default"),
            "user_id": str(getattr(request, "user_id", "") or md.get("user_id") or ""),
        },
    )
    meta["audit"] = {
        "subsystem": "tool_fast_path",
        "allowed": True,
        "risk_tier": "low",
        "permission_scope": "tier0_builtin_tool",
    }
    return meta


def _record_tool_fast_path_audit(request: Any, meta: dict[str, Any], *, success: bool) -> None:
    """Best-effort compliance trail; never blocks tool execution."""
    try:
        import asyncio

        from kernel.governance.compliance_audit_store import record_compliance_event

        md = dict(request.metadata or {})
        coro = record_compliance_event(
            tenant_id=str(md.get("tenant_id") or "default"),
            session_id=str(getattr(request, "session_id", "") or ""),
            user_id=str(getattr(request, "user_id", "") or md.get("user_id") or ""),
            frameworks=["tier0_tool"],
            violations=[] if success else ["tool_execution_failed"],
            allowed=success,
            payload={
                "route": meta.get("route"),
                "tool_name": meta.get("tool_name"),
                "registry_agent": meta.get("registry_agent"),
                "capability_type": meta.get("capability_type"),
            },
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as exc:
        logger.warning("tool_fast_path_audit_skipped", error=str(exc))


async def run_tool_fast_path(request: Any) -> Any:
    """Execute ToolAgent once and return KernelResponse."""
    from agents.base import TaskMessage
    from agents.tool_agent import ToolAgent
    from kernel.cognitive_kernel import KernelResponse

    t0 = time.monotonic()
    task_id = str((request.metadata or {}).get("request_id") or uuid.uuid4())
    cap, reg = get_manifest().resolve_capability_alias("tool")
    task = TaskMessage(
        task_id=task_id,
        agent_type=reg,
        query=request.query,
        params=dict(request.metadata or {}),
        session_id=request.session_id or "",
        user_id=getattr(request, "user_id", "") or "",
    )
    result = await ToolAgent().execute(task)
    total_ms = int((time.monotonic() - t0) * 1000)
    lock = (request.metadata or {}).get("intent_lock") or {}
    task_type = str(lock.get("task_type") or "tool")
    tool_name = (result.metadata or {}).get("tool_name") if result.metadata else None
    gov = _tool_governance_meta(request, task_type=task_type, tool_name=tool_name)

    if result.status == "success" and (result.content or "").strip():
        _record_tool_fast_path_audit(request, gov, success=True)
        return KernelResponse(
            content=result.content,
            session_id=request.session_id,
            route="tool_fast_path",
            validation_score=0.92,
            passed_validation=True,
            hallucination_risk=0.05,
            intent_category=task_type,
            intent_complexity="L1",
            context_latency_ms=0,
            total_latency_ms=total_ms,
            metadata={
                **gov,
                "tool_name": tool_name,
                "intent_lock": lock,
            },
            result_refs=[],
        )

    err = result.error or "tool execution failed"
    gov_err = {**gov, "audit": {**(gov.get("audit") or {}), "allowed": False}}
    _record_tool_fast_path_audit(request, gov_err, success=False)
    return KernelResponse(
        content=f"工具调用未能完成：{err}",
        session_id=request.session_id,
        route="tool_fast_path_error",
        validation_score=0.5,
        passed_validation=False,
        hallucination_risk=0.2,
        intent_category=task_type,
        intent_complexity="L1",
        context_latency_ms=0,
        total_latency_ms=total_ms,
        metadata={**gov_err, "error": err},
    )


async def stream_tool_fast_path(request: Any):
    """Yield SSE events for tool fast path."""
    import asyncio

    from kernel.cognitive_kernel import _STREAM_CHUNK_SIZE, _STREAM_DELAY

    resp = await run_tool_fast_path(request)
    cap, reg = get_manifest().resolve_capability_alias("tool")
    yield {
        "type": "reasoning_step",
        "data": {
            "id": "tool_fast_path",
            "stage": "ROUTE",
            "content": f"工具快速路径 ({reg})",
            "node_id": "node_tool_fast",
            "status": "done",
        },
    }
    text = resp.content or ""
    for i in range(0, len(text), _STREAM_CHUNK_SIZE):
        yield {"type": "delta", "data": {"text": text[i : i + _STREAM_CHUNK_SIZE]}}
        await asyncio.sleep(_STREAM_DELAY)
    yield {
        "type": "final_answer",
        "data": {
            "content": text,
            "route": resp.route,
            "validation_score": resp.validation_score,
            "passed_validation": resp.passed_validation,
            "metadata": dict(resp.metadata or {}),
            "execution_graph": {
                "route": resp.route,
                "agent_type": reg,
                "capability_type": cap,
                "governance": dict(resp.metadata or {}),
            },
        },
    }