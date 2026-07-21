"""Runtime lookup and dispatch — Gateway uses this only."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

RuntimeHandler = Callable[..., Awaitable[Any]]

_HANDLERS: dict[str, RuntimeHandler] = {}


def register_runtime(name: str, handler: RuntimeHandler) -> None:
    _HANDLERS[name] = handler


def get_runtime_handler(name: str) -> RuntimeHandler | None:
    return _HANDLERS.get(name)


def list_runtimes() -> list[str]:
    return sorted(_HANDLERS.keys())


async def dispatch_runtime(
    name: str,
    *,
    request: Any,
    ctx: Any,
    query: str = "",
    event_cb: Any = None,
) -> Any:
    from kernel.runtime.registry_governance import evaluate_registry_dispatch

    gate = evaluate_registry_dispatch(name, request=request, ctx=ctx)
    if ctx is not None:
        ctx.metadata = getattr(ctx, "metadata", None) or {}
        ctx.metadata["registry_dispatch_gate"] = {
            "allowed": gate.allowed,
            "violations": list(gate.violations),
            "capability_ranking": gate.capability_ranking,
        }
    if not gate.allowed:
        from kernel.cognitive_kernel import KernelResponse

        return KernelResponse(
            content="运行时能力调度未通过治理检查。",
            session_id=getattr(request, "session_id", ""),
            route="registry_dispatch_denied",
            validation_score=1.0,
            passed_validation=False,
            hallucination_risk=0.0,
            intent_category="blocked",
            intent_complexity="guarded",
            metadata={"violations": gate.violations, "runtime": name},
        )

    from kernel.runtime.runtime_tiers import attach_tier_metadata

    attach_tier_metadata(ctx, name)

    handler = get_runtime_handler(name)
    if handler is None:
        raise KeyError(f"unknown runtime: {name}")
    if name == "data_intelligence":
        return await handler(request, ctx)
    return await handler(query or request.query, ctx, event_cb=event_cb)


def _register_defaults() -> None:
    if _HANDLERS:
        return

    async def _executive(query: str, ctx: Any, event_cb: Any = None) -> Any:
        from kernel.runtime.cognitive_executive import CognitiveExecutive

        return await CognitiveExecutive().execute(query, ctx, event_cb=event_cb)

    async def _data_intelligence(request: Any, ctx: Any) -> Any:
        from services.data_intelligence_runtime import run_data_intelligence_turn

        return await run_data_intelligence_turn(request, ctx)

    async def _multi_goal(request: Any, ctx: Any, event_cb: Any = None) -> Any:
        from kernel.runtime.multi_question_runtime import run_multi_question

        mq = await run_multi_question(request, event_cb=event_cb)
        if mq is None:
            from kernel.runtime.cognitive_executive import CognitiveExecutive

            return await CognitiveExecutive().execute(request.query, ctx, event_cb=event_cb)
        return mq

    register_runtime("cognitive_executive", _executive)
    register_runtime("data_intelligence", _data_intelligence)
    register_runtime("multi_goal", _multi_goal)


def ensure_runtimes_registered() -> None:
    _register_defaults()