"""
OpenAI-compatible LLM adapter with graceful connection error handling.
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from infra.observability.logger import get_logger
from infra.observability.metrics import LLM_CALLS_TOTAL, LLM_LATENCY, LLM_TOKENS_USED
from infra.observability.tracer import get_tracer
from model.dashscope_utils import dashscope_proxy_allowlist, resolve_dashscope_api_key
from model.llm_adapter.base import BaseLLMAdapter, LLMConfig, LLMMessage, LLMResponse

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """
    Adapter for any OpenAI-compatible REST API:
    OpenAI, DashScope/Qwen, Azure OpenAI, vLLM, Ollama, etc.
    """

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._client = None
        self._http_client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            import httpx

            timeout = httpx.Timeout(
                connect=min(15.0, float(self.config.timeout)),
                read=float(self.config.timeout),
                write=min(15.0, float(self.config.timeout)),
                pool=min(15.0, float(self.config.timeout)),
            )
            # Use env proxy settings first, but keep a fallback without proxy.
            self._http_client = httpx.AsyncClient(
                trust_env=True,
                timeout=timeout,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
            )
            self._client = AsyncOpenAI(
                api_key=resolve_dashscope_api_key(self.config.api_key),
                base_url=self.config.base_url or None,
                timeout=timeout,
                http_client=self._http_client,
            )
        return self._client

    async def _try_complete(self, use_proxy: bool, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        from openai import AsyncOpenAI
        import httpx

        timeout = httpx.Timeout(
            connect=min(15.0, float(self.config.timeout)),
            read=float(self.config.timeout),
            write=min(15.0, float(self.config.timeout)),
            pool=min(15.0, float(self.config.timeout)),
        )
        http_client = httpx.AsyncClient(
            trust_env=use_proxy,
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
        )
        client = AsyncOpenAI(
            api_key=resolve_dashscope_api_key(self.config.api_key),
            base_url=self.config.base_url or None,
            timeout=timeout,
            http_client=http_client,
        )
        oai_msgs = [self._to_oai(m) for m in messages]
        extra: dict = {}
        if "qwen3" in self.config.model.lower():
            extra["extra_body"] = {"enable_thinking": False}
        try:
            resp = await client.chat.completions.create(
                model=self.config.model,
                messages=oai_msgs,
                temperature=kwargs.get("temperature", self.config.temperature),
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                stream=False,
                **extra,
            )
            usage = resp.usage
            content = next((choice.message.content for choice in resp.choices if choice.message and choice.message.content), "")
            return LLMResponse(
                content=content,
                model=resp.model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                finish_reason=(resp.choices[0].finish_reason or "stop") if resp.choices else "stop",
                raw={},
            )
        finally:
            await http_client.aclose()

    async def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        with tracer.start_as_current_span("llm.complete") as span:
            span.set_attribute("llm.provider", self.config.provider)
            span.set_attribute("llm.model", self.config.model)
            t0 = time.monotonic()
            try:
                try:
                    resp = await self._try_complete(True, messages, **kwargs)
                except Exception as proxy_exc:
                    logger.warning("LLM call via proxy failed, retrying direct", error=str(proxy_exc), model=self.config.model)
                    resp = await self._try_complete(False, messages, **kwargs)
                latency = time.monotonic() - t0
                LLM_CALLS_TOTAL.labels(provider=self.config.provider, model=self.config.model, status="ok").inc()
                LLM_LATENCY.labels(provider=self.config.provider, model=self.config.model).observe(latency)
                return resp
            except Exception as exc:
                LLM_CALLS_TOTAL.labels(provider=self.config.provider, model=self.config.model, status="error").inc()
                logger.error("LLM call failed", error=str(exc), model=self.config.model)
                raise

    async def stream(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[str]:
        async def _stream_once(use_proxy: bool):
            from openai import AsyncOpenAI
            import httpx
            timeout = httpx.Timeout(connect=min(15.0, float(self.config.timeout)), read=float(self.config.timeout), write=min(15.0, float(self.config.timeout)), pool=min(15.0, float(self.config.timeout)))
            http_client = httpx.AsyncClient(trust_env=use_proxy, timeout=timeout, limits=httpx.Limits(max_keepalive_connections=10, max_connections=50))
            client = AsyncOpenAI(api_key=resolve_dashscope_api_key(self.config.api_key), base_url=self.config.base_url or None, timeout=timeout, http_client=http_client)
            oai_msgs = [self._to_oai(m) for m in messages]
            extra: dict = {}
            if "qwen3" in self.config.model.lower():
                extra["extra_body"] = {"enable_thinking": False}
            try:
                stream = await client.chat.completions.create(
                    model=self.config.model,
                    messages=oai_msgs,
                    temperature=kwargs.get("temperature", self.config.temperature),
                    max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                    stream=True,
                    **extra,
                )
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            finally:
                await http_client.aclose()

        try:
            async for part in _stream_once(True):
                yield part
        except Exception as proxy_exc:
            logger.warning("LLM stream via proxy failed, retrying direct", error=str(proxy_exc), model=self.config.model)
            async for part in _stream_once(False):
                yield part

    def _to_oai(self, m: LLMMessage) -> dict:
        msg: dict = {"role": m.role, "content": m.content}
        if m.name:
            msg["name"] = m.name
        return msg
