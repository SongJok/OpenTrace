"""
Executor — runs a single SubTask by dispatching to tool or LLM.
"""
from __future__ import annotations

from typing import Any

from agent_runtime.planner.planner import SubTask
from execution.tool_router.router import ToolRouter
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class Executor:
    """Executes a SubTask — tries tool dispatch, falls back to LLM."""

    def __init__(self) -> None:
        self._tool_router = ToolRouter()
        self._gateway = get_model_gateway()

    async def execute(self, subtask: SubTask, context: dict[str, Any]) -> str:
        with tracer.start_as_current_span("executor.execute") as span:
            span.set_attribute("subtask.id", subtask.task_id)
            span.set_attribute("subtask.description", subtask.description[:80])

            # Try tool dispatch first
            result = await self._tool_router.execute(
                intent=subtask.description,
                query=subtask.description,
            )
            if result:
                logger.debug("Subtask resolved via tool", task=subtask.task_id)
                return result

            # Fall back to LLM
            dep_context = "\n".join(
                f"{dep}: {context.get(dep, '(pending)')}"
                for dep in subtask.deps
            )
            prompt = subtask.description
            if dep_context:
                prompt = f"Previous results:\n{dep_context}\n\nTask: {subtask.description}"

            resp = await self._gateway.complete(
                messages=[LLMMessage(role="user", content=prompt)],
                role=LLMRole.QUERY,
                temperature=0.3,
            )
            return resp.content
