"""
Agent Core — ReAct-style base agent using ToolRouter for action dispatch.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.observability.metrics import AGENT_STEPS, AGENT_TASKS_TOTAL
from infra.observability.tracer import get_tracer
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class AgentContext:
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    query: str = ""
    scratchpad: list[str] = field(default_factory=list)
    tool_results: dict[str, Any] = field(default_factory=dict)
    step: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    """
    ReAct-style agent: Thought -> Action -> Observation loop.
    Uses ToolRouter for real tool dispatch.
    """

    SYSTEM_PROMPT = """\
You are a capable AI agent. Work step-by-step.
For each step output EXACTLY one of:
  Thought: <your reasoning>
  Action: <tool_name>(<arg>)
  Answer: <final answer>

Do not combine lines. Wait for tool observations before continuing.
"""

    def __init__(self, name: str = "agent") -> None:
        self.name = name
        self._gateway = get_model_gateway()
        self.status = AgentStatus.IDLE
        self._tool_router = None

    def _get_tool_router(self):
        if self._tool_router is None:
            from execution.tool_router.router import ToolRouter
            self._tool_router = ToolRouter()
        return self._tool_router

    async def run(
        self,
        query: str,
        session_id: str = "",
        tools: Optional[dict[str, Any]] = None,
    ) -> str:
        with tracer.start_as_current_span(f"agent.{self.name}.run") as span:
            ctx = AgentContext(query=query, session_id=session_id)
            self.status = AgentStatus.RUNNING
            AGENT_TASKS_TOTAL.labels(agent_type=self.name, status="started").inc()

            messages: list[LLMMessage] = [
                LLMMessage(role="system", content=self.SYSTEM_PROMPT),
                LLMMessage(role="user", content=query),
            ]

            answer: Optional[str] = None

            try:
                for step in range(settings.max_agent_steps):
                    ctx.step = step
                    resp = await asyncio.wait_for(
                        self._gateway.complete(
                            messages=messages, role=LLMRole.QUERY, temperature=0.1
                        ),
                        timeout=settings.agent_timeout,
                    )
                    text = resp.content.strip()
                    messages.append(LLMMessage(role="assistant", content=text))
                    ctx.scratchpad.append(text)

                    # Answer reached
                    if text.startswith("Answer:"):
                        answer = text[len("Answer:"):].strip()
                        break

                    # Action — dispatch via ToolRouter
                    if text.startswith("Action:"):
                        observation = await self._execute_action(
                            text, tools or {}
                        )
                        messages.append(
                            LLMMessage(role="user", content=f"Observation: {observation}")
                        )
                        ctx.tool_results[f"step_{step}"] = observation
                        continue

                    # Thought — no action needed, continue
                    if text.startswith("Thought:"):
                        continue

                    # Unstructured — try to extract Answer anyway
                    if "Answer:" in text:
                        answer = text.split("Answer:", 1)[-1].strip()
                        break

                AGENT_STEPS.labels(agent_type=self.name).observe(ctx.step + 1)
                self.status = AgentStatus.DONE
                AGENT_TASKS_TOTAL.labels(agent_type=self.name, status="success").inc()
                span.set_attribute("agent.steps", ctx.step + 1)
                return answer or "Agent did not reach a final answer."

            except Exception as exc:  # noqa: BLE001
                self.status = AgentStatus.FAILED
                AGENT_TASKS_TOTAL.labels(agent_type=self.name, status="failed").inc()
                logger.error("Agent failed", agent=self.name, error=str(exc))
                raise

    async def _execute_action(
        self, text: str, extra_tools: dict[str, Any]
    ) -> str:
        """
        Parse 'Action: tool_name(arg)' and dispatch:
          1. extra_tools dict (caller-provided callables)
          2. ToolRouter (registry-backed tools)
        """
        action_line = text[len("Action:"):].strip()

        # Parse tool_name(arg) format
        m = re.match(r"([\w_]+)\s*\((.*)\)\s*$", action_line, re.DOTALL)
        if m:
            tool_name = m.group(1).strip()
            arg = m.group(2).strip().strip('"\'')
        else:
            # Bare tool name, no parens
            tool_name = action_line.split()[0] if action_line.split() else ""
            arg = action_line[len(tool_name):].strip()

        # 1. Extra tools dict
        if tool_name in extra_tools:
            try:
                result = extra_tools[tool_name]
                if callable(result):
                    result = await result(arg) if asyncio.iscoroutinefunction(result) else result(arg)
                return str(result)
            except Exception as exc:  # noqa: BLE001
                return f"Tool error ({tool_name}): {exc}"

        # 2. ToolRouter
        router = self._get_tool_router()
        result = await router.execute(
            intent=f"{tool_name} {arg}",
            query=arg,
            tool_name=tool_name,
        )
        if result is not None:
            return result

        return f"Unknown tool: {tool_name}. Available: {self._get_tool_router().registry.list_all()}"
