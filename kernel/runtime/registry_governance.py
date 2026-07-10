"""Pre-dispatch governance for runtime registry — capability contract + allowlist."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RegistryDispatchGate:
    allowed: bool = True
    violations: list[str] = field(default_factory=list)
    capability_ranking: list[dict[str, Any]] = field(default_factory=list)


def evaluate_registry_dispatch(
    runtime_name: str,
    *,
    request: Any,
    ctx: Any,
) -> RegistryDispatchGate:
    """Validate runtime selection against constraints before handler invocation."""
    gate = RegistryDispatchGate(allowed=True)
    md = dict(getattr(request, "metadata", None) or {})
    lock = md.get("intent_lock") or {}
    allowed_caps = list(lock.get("allowed_capabilities") or getattr(ctx, "allowed_capabilities", None) or [])
    disallowed = set(lock.get("disallowed_capabilities") or getattr(ctx, "disallowed_capabilities", None) or [])

    intent = str(
        md.get("task_type")
        or getattr(ctx, "task_type", None)
        or (md.get("goal_graph") or {}).get("intent_category")
        or "general"
    )

    runtime_caps: list[str] = []
    if runtime_name == "data_intelligence":
        runtime_caps = ["data.query"]
    elif runtime_name == "multi_goal":
        runtime_caps = ["planner", "model.answer"]
    elif allowed_caps:
        runtime_caps = list(allowed_caps)
    else:
        # 无 intent_lock 时勿默认挂上 rag/web（会与 general_qa 的 disallowed 误杀整轮）
        runtime_caps = ["model.answer"]

    try:
        from kernel.capability_runtime.selector import rank_capabilities_for_intent

        gate.capability_ranking = rank_capabilities_for_intent(
            runtime_caps,
            intent_category=intent,
            allowed=allowed_caps or None,
        )
    except Exception as exc:
        logger.debug("registry_dispatch_rank_skipped", error=str(exc))

    if allowed_caps:
        for cap in runtime_caps:
            ctype = cap.split(".")[0] if "." in cap else cap
            if cap in disallowed or ctype in disallowed:
                gate.violations.append(f"capability_denied:{cap}")
        if gate.violations:
            gate.allowed = False

    if runtime_name == "data_intelligence":
        blocked = (
            "data.query" in disallowed
            or "data_query" in disallowed
            or "data" in disallowed
        )
        if blocked or (
            allowed_caps and "data.query" not in allowed_caps and "data_query" not in allowed_caps
        ):
            gate.allowed = False
            gate.violations.append("data_intelligence_denied")

    try:
        from kernel.governance.execution_guardrails import ExecutionGuardrails

        guard = ExecutionGuardrails()
        caps_to_check = runtime_caps[:8]
        if allowed_caps:
            caps_to_check = [c for c in caps_to_check if c in allowed_caps]
        for cap in caps_to_check:
            gr = guard.evaluate_dispatch(
                cap,
                allowed_list=allowed_caps or None,
                disallowed_list=list(disallowed) or None,
            )
            if not gr.allowed:
                gate.allowed = False
                gate.violations.extend(gr.violations or [])
    except Exception as exc:
        logger.debug("registry_dispatch_guardrails_skipped", error=str(exc))

    if bool(getattr(settings, "kernel_registry_dispatch_strict", False)) and gate.violations:
        gate.allowed = False

    return gate