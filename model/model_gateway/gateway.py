"""
Model Gateway — single entry point for all LLM calls.
Upgraded with per-role circuit breaker to prevent cascading failures.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any, AsyncIterator, Iterator, Optional

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.identity.system_identity import (
    CANONICAL_IDENTITY_RESPONSE,
    enforce_identity_output,
    is_identity_user_query,
    last_user_text,
    merge_system_identity,
)
from model.llm_adapter.base import BaseLLMAdapter, LLMConfig, LLMMessage, LLMResponse
from model.llm_adapter.openai_adapter import OpenAICompatibleAdapter

logger = get_logger(__name__)
tracer = get_tracer(__name__)

_model_call_capture: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "model_call_capture", default=None
)


@contextmanager
def capture_model_calls() -> Iterator[list[dict[str, Any]]]:
    """Capture successful provider calls made while executing one user turn."""
    calls: list[dict[str, Any]] = []
    token = _model_call_capture.set(calls)
    try:
        yield calls
    finally:
        _model_call_capture.reset(token)


def _record_model_call(*, role: "LLMRole", model: str, latency_ms: int) -> None:
    calls = _model_call_capture.get()
    if calls is not None:
        calls.append(
            {
                "id": f"mc_{uuid.uuid4().hex}",
                "role": role.value,
                "model": model,
                "latency_ms": latency_ms,
            }
        )


def _post_process_identity_response(messages: list[LLMMessage], content: str) -> str:
    return enforce_identity_output(content, last_user_text(messages))


def _offline_fallback_response(messages: list[LLMMessage], role: LLMRole) -> LLMResponse:
    user_text = (last_user_text(messages) or '').strip()
    if role == LLMRole.ROUTER:
        content = '{"route": "complex", "difficulty": "simple"}'
    elif role == LLMRole.IDENTITY:
        content = CANONICAL_IDENTITY_RESPONSE
    elif role == LLMRole.FAST:
        content = '我目前处于离线降级模式，暂时无法提供完整回答。请稍后重试或换一种更具体的问法。'
    elif role == LLMRole.CHEAP_CRITIC:
        content = '{"verdict": "pass", "confidence": 0.5, "issues": []}'
    elif role == LLMRole.KNOWLEDGE:
        content = '我目前处于离线降级模式，暂时无法查询知识库。请稍后重试。'
    elif role == LLMRole.PLANNING:
        content = '{"subtasks": [{"agent_type": "tool", "query": "' + user_text.replace('"', '\\"')[:120] + '"}], "merge_strategy": "prioritized", "max_parallel": 1}'
    elif any(k in user_text for k in ['你是谁', '你叫什么', 'who are you', 'identity']):
        content = CANONICAL_IDENTITY_RESPONSE
    elif any(k in user_text for k in ['你能做什么', '有什么能力', '怎么用', '如何使用', 'help', '功能', '能力']):
        content = '我是 OpenTrace，一个基于认知内核构建的 AI 系统。\n\n我可以帮你进行：\n- 对话问答\n- 文档检索与总结\n- 数据库查询与分析\n- 任务与记忆管理\n- 集成与技能管理\n- 审计、追踪与调试\n\n如果你告诉我具体目标，我可以直接帮你操作。'
    elif any(k in user_text for k in ['时间', '几点', '现在几点', '日期', '今天几号']):
        content = '当前模型服务暂时不可用，但我可以建议你直接查看系统时间，或者告诉我你所在时区/地区，我会帮你组织查询方式。'
    elif any(k in user_text for k in ['天气', 'weather']):
        content = '当前模型服务暂时不可用，但我可以帮你整理天气查询所需的城市/地点信息，或者接入天气工具后再自动查询。'
    elif any(k in user_text for k in ['总结', '概括', '归纳', '文档']):
        content = '当前模型服务暂时不可用，但我可以先给你一个离线模式的简要回复：请提供文档或更具体的问题，我会尽力整理。'
    else:
        content = '我目前处于离线降级模式，暂时无法调用模型服务，但仍可以基于已有上下文回答。请稍后重试，或换一种更具体的问法。'
    return LLMResponse(content=content, model='offline-fallback', raw={'fallback': True, 'role': role.value, 'user_text': user_text})


class LLMRole(str, Enum):
    QUERY = "query"
    COMPRESS = "compress"
    PLANNING = "planning"
    ROUTER = "router"             # JuniorShort 1.7B — L1 classification
    FAST = "fast"                 # MiddleShort 8B — simple answers
    CHEAP_CRITIC = "cheap_critic" # SeniorShort 14B — lightweight critique
    KNOWLEDGE = "knowledge"       # SeniorShort 14B — knowledge Q&A
    IDENTITY = "identity"         # MinShort 0.6B — personalized identity response
    VISION = "vision"             # Vision-capable — image/chart interpretation


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------
class CircuitBreaker:
    """
    Simple three-state circuit breaker: closed → open → half-open.
    CLOSED  — normal operation
    OPEN    — failing; reject calls for `recovery_timeout` seconds
    HALF-OPEN — one probe call allowed; success closes, failure re-opens
    """

    _CLOSED = "closed"
    _OPEN = "open"
    _HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.state: str = self._CLOSED

    def allow_request(self) -> bool:
        if self.state == self._CLOSED:
            return True
        if self.state == self._OPEN:
            if time.monotonic() - self.last_failure_time >= self.recovery_timeout:
                self.state = self._HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = self._CLOSED

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = self._OPEN
            logger.warning(
                "Circuit breaker OPEN",
                failures=self.failure_count,
                recovery_in=self.recovery_timeout,
            )


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------
def _build_config(role: LLMRole) -> LLMConfig:
    s = settings
    if role == LLMRole.QUERY:
        return LLMConfig(
            provider=s.default_llm_query_provider,
            model=s.default_llm_query_model,
            base_url=s.default_llm_query_base_url,
            api_key=s.default_llm_query_api_key,
        )
    if role == LLMRole.COMPRESS:
        return LLMConfig(
            provider=s.default_llm_compress_provider,
            model=s.default_llm_compress_model,
            base_url=s.default_llm_compress_base_url,
            api_key=s.default_llm_compress_api_key,
        )
    if role == LLMRole.PLANNING:
        return LLMConfig(
            provider=s.default_llm_planing_provider,
            model=s.default_llm_planing_model,
            base_url=s.default_llm_planing_base_url,
            api_key=s.default_llm_planing_api_key,
        )
    if role == LLMRole.ROUTER:
        return LLMConfig(
            provider=s.default_llm_juniorshort_provider,
            model=s.default_llm_juniorshort_model,
            base_url=s.default_llm_juniorshort_base_url,
            api_key=s.default_llm_juniorshort_api_key,
        )
    if role == LLMRole.FAST:
        return LLMConfig(
            provider=s.default_llm_middleshort_provider,
            model=s.default_llm_middleshort_model,
            base_url=s.default_llm_middleshort_base_url,
            api_key=s.default_llm_middleshort_api_key,
        )
    if role == LLMRole.CHEAP_CRITIC:
        return LLMConfig(
            provider=s.default_llm_seniorshort_provider,
            model=s.default_llm_seniorshort_model,
            base_url=s.default_llm_seniorshort_base_url,
            api_key=s.default_llm_seniorshort_api_key,
        )
    if role == LLMRole.KNOWLEDGE:
        return LLMConfig(
            provider=s.default_llm_seniorshort_provider,
            model=s.default_llm_seniorshort_model,
            base_url=s.default_llm_seniorshort_base_url,
            api_key=s.default_llm_seniorshort_api_key,
        )
    if role == LLMRole.IDENTITY:
        return LLMConfig(
            provider=s.default_llm_minshort_provider,
            model=s.default_llm_minshort_model,
            base_url=s.default_llm_minshort_base_url,
            api_key=s.default_llm_minshort_api_key,
            temperature=0.7,
            max_tokens=256,
            timeout=8,
        )
    if role == LLMRole.VISION:
        return LLMConfig(
            provider=s.default_llm_vision_provider,
            model=s.default_llm_vision_model,
            base_url=s.default_llm_vision_base_url,
            api_key=s.default_llm_vision_api_key,
            temperature=0.3,
            max_tokens=2048,
            timeout=60,
        )
    return LLMConfig(
        provider=s.default_llm_query_provider,
        model=s.default_llm_query_model,
        base_url=s.default_llm_query_base_url,
        api_key=s.default_llm_query_api_key,
    )


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------
class ModelGateway:
    """
    Central gateway for all model calls.
    Features:
      - Per-role adapter instances
      - Fallback chain (role → fallback_roles)
      - Per-role circuit breaker (stops hammering failed endpoints)
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        self._adapters: dict[str, BaseLLMAdapter] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout

    def _get_adapter(self, role: LLMRole) -> BaseLLMAdapter:
        key = role.value
        if key not in self._adapters:
            self._adapters[key] = OpenAICompatibleAdapter(_build_config(role))
        return self._adapters[key]

    def _classify_exception(self, exc: Exception) -> str:
        from httpx import ConnectError, ProxyError, TimeoutException

        if isinstance(exc, TimeoutException):
            return "timeout"
        if isinstance(exc, (ConnectError, ProxyError)):
            return "connectivity"

        msg = str(exc).lower()
        if any(
            k in msg
            for k in [
                "authentication",
                "api key",
                "unauthorized",
                "invalid api key",
                "allocationquota",
                "free tier",
                "quota has been exhausted",
                "payment information",
                "arrearage",
                "overdue payment",
                "account is in good standing",
            ]
        ):
            return "auth"
        if "403" in msg or "forbidden" in msg:
            return "auth"
        if any(k in msg for k in ["rate limit", "too many requests", "429"]):
            return "rate_limit"
        if any(k in msg for k in ["timeout", "timed out", "read timeout", "connect timeout"]):
            return "timeout"
        if any(k in msg for k in ["name or service not known", "nodename", "dns", "resolve", "connection error", "connect error", "proxy"]):
            return "connectivity"
        if any(k in msg for k in ["model not found", "404", "not found"]):
            return "model_not_found"
        return "unknown"

    def _retry_policy(self, exc: Exception) -> tuple[bool, float]:
        classification = self._classify_exception(exc)
        if classification in {"auth", "model_not_found"}:
            return False, 0.0
        if classification == "rate_limit":
            return True, 1.5
        if classification in {"timeout", "connectivity"}:
            return True, 0.6
        return True, 0.4

    async def _complete_with_retry(self, adapter: BaseLLMAdapter, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        last_exc: Exception | None = None
        max_attempts = int(kwargs.pop("max_attempts", 3))
        for attempt in range(max_attempts):
            try:
                return await adapter.complete(messages, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                should_retry, base_delay = self._retry_policy(exc)
                if attempt >= max_attempts - 1 or not should_retry:
                    break
                await asyncio.sleep(base_delay * (2 ** attempt))
        assert last_exc is not None
        raise last_exc

    def _get_cb(self, role: LLMRole) -> CircuitBreaker:
        key = role.value
        if key not in self._circuit_breakers:
            self._circuit_breakers[key] = CircuitBreaker(
                failure_threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout,
            )
        return self._circuit_breakers[key]

    async def complete(
        self,
        messages: list[LLMMessage],
        role: LLMRole = LLMRole.QUERY,
        fallback_roles: Optional[list[LLMRole]] = None,
        **kwargs,
    ) -> LLMResponse:
        model_override = str(kwargs.pop("model_override", "") or "").strip()
        with tracer.start_as_current_span("model_gateway.complete") as span:
            span.set_attribute("llm.role", role.value)
            # Query is explicitly OpenAI-primary.  Knowledge/Qwen is the
            # configured, observable provider degradation and is only added
            # when the caller did not provide a stricter chain.
            candidates = [role] + (
                fallback_roles if fallback_roles is not None else ([LLMRole.KNOWLEDGE] if role == LLMRole.QUERY else [])
            )
            last_exc: Optional[Exception] = None

            prepared_messages = merge_system_identity(messages)
            user_text = last_user_text(prepared_messages)
            for candidate in candidates:
                cb = self._get_cb(candidate)
                if not cb.allow_request():
                    logger.warning(
                        "Circuit breaker open — skipping role",
                        role=candidate.value,
                        state=cb.state,
                    )
                    continue
                try:
                    adapter = self._get_adapter(candidate)
                    if model_override and candidate == role:
                        adapter = OpenAICompatibleAdapter(
                            dataclasses.replace(adapter.config, model=model_override)
                        )
                    t0 = time.monotonic()
                    result = await self._complete_with_retry(adapter, prepared_messages, **kwargs)
                    result.content = enforce_identity_output(result.content, user_text)
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    logger.info(
                        "LLM call success",
                        role=candidate.value,
                        latency_ms=latency_ms,
                        model=adapter.config.model,
                    )
                    cb.record_success()
                    _record_model_call(
                        role=candidate,
                        model=str(adapter.config.model or ""),
                        latency_ms=latency_ms,
                    )
                    span.set_attribute("llm.resolved_role", candidate.value)
                    span.set_attribute("llm.latency_ms", latency_ms)
                    try:
                        from infra.observability.turn_metering import add_llm_usage

                        add_llm_usage(
                            prompt_tokens=int(result.prompt_tokens or 0),
                            completion_tokens=int(result.completion_tokens or 0),
                        )
                    except Exception:
                        pass
                    return result
                except Exception as exc:  # noqa: BLE001
                    latency_ms = int((time.monotonic() - t0) * 1000) if 't0' in locals() else 0
                    cb.record_failure()
                    logger.warning(
                        "Model call failed",
                        role=candidate.value,
                        error=str(exc),
                        error_class=self._classify_exception(exc),
                        cb_state=cb.state,
                        latency_ms=latency_ms,
                    )
                    last_exc = exc
                    # A payment/quota/auth/model error will not be repaired by
                    # another Qwen role using the same provider account.
                    if self._classify_exception(exc) in {"auth", "model_not_found"}:
                        break

            logger.warning(
                "All LLM candidates failed; using offline fallback when policy allows",
                candidates=[r.value for r in candidates],
                error=str(last_exc) if last_exc else None,
            )
            if bool(getattr(settings, "kernel_all_questions_require_model", True)) and role == LLMRole.QUERY and self._classify_exception(last_exc) not in {"auth", "model_not_found"}:
                raise RuntimeError("primary_model_unavailable") from last_exc
            if is_identity_user_query(user_text):
                return LLMResponse(content=CANONICAL_IDENTITY_RESPONSE, model='identity-fallback', raw={'fallback': True, 'role': role.value, 'user_text': user_text})
            return _offline_fallback_response(prepared_messages, role)

    async def stream(
        self,
        messages: list[LLMMessage],
        role: LLMRole = LLMRole.QUERY,
        **kwargs,
    ) -> AsyncIterator[str]:
        prepared_messages = merge_system_identity(messages)
        user_text = last_user_text(prepared_messages)
        cb = self._get_cb(role)
        if not cb.allow_request():
            logger.warning("Circuit breaker open; using offline fallback when policy allows", role=role.value)
            if bool(getattr(settings, "kernel_all_questions_require_model", True)) and role == LLMRole.QUERY:
                raise RuntimeError("primary_model_circuit_open")
            fallback = _offline_fallback_response(prepared_messages, role).content
            if fallback:
                step = 256
                for i in range(0, len(fallback), step):
                    yield fallback[i : i + step]
            return
        adapter = self._get_adapter(role)
        t0 = time.monotonic()
        buf: list[str] = []
        max_attempts = int(kwargs.pop("max_attempts", 3))
        for attempt in range(max_attempts):
            try:
                async for chunk in adapter.stream(prepared_messages, **kwargs):
                    buf.append(chunk)
                    yield chunk
                latency_ms = int((time.monotonic() - t0) * 1000)
                full_text = "".join(buf)
                enforce_identity_output(full_text, user_text)  # post-hoc validation only
                try:
                    from infra.observability.turn_metering import add_llm_usage
                    from kernel.token_counter import TokenCounter

                    tc = TokenCounter()
                    est_prompt = tc.count(
                        "\n".join(
                            str(getattr(m, "content", "") or "")
                            for m in prepared_messages
                        )
                    )
                    est_completion = tc.count(full_text)
                    add_llm_usage(
                        prompt_tokens=est_prompt,
                        completion_tokens=est_completion,
                    )
                except Exception:
                    pass
                logger.info("LLM stream success", role=role.value, latency_ms=latency_ms)
                cb.record_success()
                _record_model_call(
                    role=role,
                    model=str(adapter.config.model or ""),
                    latency_ms=latency_ms,
                )
                return
            except Exception as exc:  # noqa: BLE001
                should_retry, base_delay = self._retry_policy(exc)
                if attempt >= max_attempts - 1 or not should_retry:
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    cb.record_failure()
                    logger.warning("LLM stream failed; using offline fallback when policy allows", role=role.value, error=str(exc), error_class=self._classify_exception(exc), latency_ms=latency_ms, cb_state=cb.state)
                    if bool(getattr(settings, "kernel_all_questions_require_model", True)) and role == LLMRole.QUERY and self._classify_exception(exc) not in {"auth", "model_not_found"}:
                        raise RuntimeError("primary_model_unavailable") from exc
                    fallback = _offline_fallback_response(prepared_messages, role).content
                    if fallback:
                        step = 256
                        for i in range(0, len(fallback), step):
                            yield fallback[i : i + step]
                    return
                await asyncio.sleep(base_delay * (2 ** attempt))
                buf = []


_gateway: Optional[ModelGateway] = None


def get_model_gateway() -> ModelGateway:
    global _gateway
    if _gateway is None:
        _gateway = ModelGateway()
    return _gateway
