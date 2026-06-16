"""
工具路由 — 按意图匹配选择并安全调度工具。
"""
from __future__ import annotations

import inspect
from typing import Any, Optional

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from tools.registry.registry import ToolRegistry, ToolSpec, registry as global_registry

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class ToolRouter:
    """
    Selects and dispatches tools based on intent matching.
    Only passes kwargs the tool function actually accepts.
    """

    def __init__(self, tool_registry: Optional[ToolRegistry] = None) -> None:
        self.registry = tool_registry or global_registry

    async def select_tool(self, intent: str) -> Optional[ToolSpec]:
        with tracer.start_as_current_span("tool_router.select") as span:
            candidates = self.registry.match(intent)
            span.set_attribute("tool.candidates", len(candidates))
            if not candidates:
                logger.debug("No matching tool", intent=intent[:80])
                return None
            best = candidates[0]  # already sorted by score
            span.set_attribute("tool.selected", best.name)
            span.set_attribute("tool.score", best.score)
            logger.debug("Tool selected", tool=best.name, score=best.score)
            return best

    async def execute(
        self,
        intent: str,
        session_id: str = "",
        **kwargs: Any,
    ) -> Optional[str]:
        """
        Select the best tool and call it with only the kwargs it accepts.
        Returns None when no tool matches, error string on tool failure.
        """
        with tracer.start_as_current_span("tool_router.execute") as span:
            tool = await self.select_tool(intent)
            if tool is None:
                return None

            span.set_attribute("tool.name", tool.name)

            merged = {**kwargs, "session_id": session_id}
            safe_kwargs = _filter_kwargs(tool.fn, merged)

            try:
                result = await tool.fn(**safe_kwargs)
                return str(result) if result is not None else None
            except Exception as exc:  # noqa: BLE001
                logger.error("Tool execution failed", tool=tool.name, error=str(exc))
                return f"Tool error ({tool.name}): {exc}"

    async def execute_by_name(
        self,
        name: str,
        session_id: str = "",
        **kwargs: Any,
    ) -> Optional[str]:
        """Execute a specific tool by name, bypassing intent matching."""
        tool = self.registry.get(name)
        if tool is None:
            return None
        merged = {**kwargs, "session_id": session_id}
        safe_kwargs = _filter_kwargs(tool.fn, merged)
        try:
            result = await tool.fn(**safe_kwargs)
            return str(result) if result is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.error("Tool execution failed", tool=name, error=str(exc))
            return f"Tool error ({name}): {exc}"


def _filter_kwargs(
    fn: Any, kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Return only the kwargs that fn's signature actually accepts."""
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
        # If fn accepts **kwargs, pass everything
        for p in params.values():
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                return kwargs
        return {k: v for k, v in kwargs.items() if k in params}
    except (ValueError, TypeError):
        return kwargs
