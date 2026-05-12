"""
Base LLM Adapter — every provider implements this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # system | user | assistant | tool
    content: str | list[dict[str, Any]] | None = (
        None  # str for text, list for multimodal, None for tool-call-only msgs
    )
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None  # assistant tool_calls per OpenAI spec


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 120
    stream: bool = False


class BaseLLMAdapter(ABC):
    """Abstract base for all LLM provider adapters."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        **kwargs,
    ) -> LLMResponse:
        """Non-streaming completion."""

    @abstractmethod
    async def stream(
        self,
        messages: list[LLMMessage],
        **kwargs,
    ) -> AsyncIterator[str]:
        """Streaming completion — yields text chunks."""

    async def health_check(self) -> bool:
        """Ping the provider; return True if reachable."""
        try:
            await self.complete([LLMMessage(role="user", content="ping")])
            return True
        except Exception:  # noqa: BLE001
            return False
