"""单个 Response 生命周期内的动态大模型配置。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeLLMProfile:
    """Worker 从持久化设置解析出的 OpenAI-compatible 文本模型配置。"""

    source: str
    provider: str
    base_url: str
    api_key: str
    model: str
    models: tuple[str, ...] = ()
    api_mode: str = "chat_completions"

    def resolve_model(self, requested: str | None = None) -> str:
        candidate = str(requested or "").strip()
        allowed = {item.strip() for item in self.models if item.strip()}
        if candidate and candidate in allowed:
            return candidate
        return self.model


_runtime_profile: ContextVar[RuntimeLLMProfile | None] = ContextVar(
    "runtime_llm_profile", default=None
)


def get_runtime_llm_profile() -> RuntimeLLMProfile | None:
    return _runtime_profile.get()


def resolve_runtime_model(requested: str) -> str:
    profile = get_runtime_llm_profile()
    if profile is None:
        return requested
    return profile.resolve_model(requested)


@contextmanager
def use_runtime_llm_profile(profile: RuntimeLLMProfile | None) -> Iterator[None]:
    token = _runtime_profile.set(profile)
    try:
        yield
    finally:
        _runtime_profile.reset(token)
