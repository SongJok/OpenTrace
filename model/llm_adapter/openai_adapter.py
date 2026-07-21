"""
OpenAI-compatible LLM adapter with graceful connection error handling.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from infra.observability.logger import get_logger
from infra.observability.metrics import LLM_CALLS_TOTAL, LLM_LATENCY
from infra.observability.tracer import get_tracer
from model.dashscope_utils import resolve_dashscope_api_key
from model.llm_adapter.base import BaseLLMAdapter, LLMConfig, LLMMessage, LLMResponse

logger = get_logger(__name__)
tracer = get_tracer(__name__)


def _should_retry_without_proxy(exc: Exception) -> bool:
    """Only bypass the proxy for transport failures.

    Provider HTTP errors (invalid key, arrears, quota, bad model) are already
    definitive responses. Retrying those through a second transport used to
    add several seconds to every turn and made the UI look permanently stuck.
    """
    import httpx

    if isinstance(exc, httpx.ConnectError | httpx.ProxyError | httpx.TimeoutException):
        return True
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "connection error",
            "connect timeout",
            "proxy error",
            "name or service not known",
        )
    )


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
            import httpx
            from openai import AsyncOpenAI

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

    async def _try_complete(
        self, use_proxy: bool, messages: list[LLMMessage], **kwargs
    ) -> LLMResponse:
        if not self.config.api_key:
            raise RuntimeError("provider_api_key_missing")
        if self._uses_responses_api:
            return await self._try_responses_complete(use_proxy, messages, **kwargs)
        import httpx
        from openai import AsyncOpenAI

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
            extra["extra_body"] = {"enable_thinking": self._qwen_thinking_enabled(kwargs)}
        # OpenAI-compatible chat endpoints accept the same function schema as
        # the Responses API.  Only include optional fields when requested so
        # legacy providers keep their exact request shape.
        optional = {
            "tools": self._chat_tools(kwargs.get("tools") or []),
            "tool_choice": kwargs.get("tool_choice"),
            "parallel_tool_calls": kwargs.get("parallel_tool_calls"),
        }
        extra.update({k: v for k, v in optional.items() if v is not None and (k != "tools" or v)})
        try:
            resp = await client.chat.completions.create(
                model=self.config.model,
                messages=oai_msgs,
                temperature=kwargs.get("temperature", self.config.temperature),
                max_tokens=kwargs.get(
                    "max_tokens", kwargs.get("max_output_tokens", self.config.max_tokens)
                ),
                stream=False,
                **extra,
            )
            usage = resp.usage
            content = next(
                (
                    choice.message.content
                    for choice in resp.choices
                    if choice.message and choice.message.content
                ),
                "",
            )
            raw_calls = (
                list(getattr(resp.choices[0].message, "tool_calls", None) or [])
                if resp.choices
                else []
            )
            tool_calls = []
            for call in raw_calls:
                function = getattr(call, "function", None)
                tool_calls.append(
                    {
                        "id": str(getattr(call, "id", "") or ""),
                        "type": "function",
                        "name": str(getattr(function, "name", "") or ""),
                        "arguments": str(getattr(function, "arguments", "{}") or "{}"),
                        "call_id": str(getattr(call, "id", "") or ""),
                    }
                )
            return LLMResponse(
                content=content,
                model=resp.model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                finish_reason=(resp.choices[0].finish_reason or "stop") if resp.choices else "stop",
                tool_calls=tool_calls,
                raw={"transport": "chat.completions"},
            )
        finally:
            await http_client.aclose()

    @property
    def _uses_responses_api(self) -> bool:
        """Select the native Responses transport for OpenAI accounts.

        DashScope, vLLM and other OpenAI-compatible endpoints generally only
        implement Chat Completions, so ``auto`` remains deliberately
        conservative and switches only for the official OpenAI endpoint or an
        explicit ``api_mode=responses`` configuration.
        """
        mode = str(self.config.api_mode or "auto").lower()
        if mode == "responses":
            return True
        if mode == "chat_completions":
            return False
        provider = str(self.config.provider or "").lower()
        base_url = str(self.config.base_url or "").lower()
        return (
            provider in {"openai", "openai api", "openai-compatible"}
            or "api.openai.com" in base_url
        )

    @staticmethod
    def _response_input(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                # Responses uses typed function_call_output items instead of
                # the Chat Completions ``role=tool`` envelope.
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id or "",
                        "output": message.content or "",
                    }
                )
                continue
            if message.tool_calls:
                for call in message.tool_calls:
                    function = call.get("function") if isinstance(call, dict) else None
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": str(
                                (call or {}).get("call_id") or (call or {}).get("id") or ""
                            ),
                            "name": str(
                                (function or {}).get("name") or (call or {}).get("name") or ""
                            ),
                            "arguments": str(
                                (function or {}).get("arguments")
                                or (call or {}).get("arguments")
                                or "{}"
                            ),
                        }
                    )
                if message.content:
                    items.append({"role": "assistant", "content": message.content})
                continue
            item: dict[str, Any] = {"role": message.role, "content": message.content or ""}
            if message.name:
                item["name"] = message.name
            if message.tool_call_id:
                item["call_id"] = message.tool_call_id
            if message.tool_calls:
                item["tool_calls"] = message.tool_calls
            items.append(item)
        return items

    @staticmethod
    def _chat_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Responses function definitions to Chat Completions shape."""
        normalized: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            if isinstance(tool.get("function"), dict):
                normalized.append(tool)
            elif tool.get("type") == "function" and tool.get("name"):
                normalized.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.get("name"),
                            "description": tool.get("description", ""),
                            "parameters": tool.get("parameters")
                            or {"type": "object", "properties": {}},
                        },
                    }
                )
        return normalized

    @staticmethod
    def _parse_response_output(
        response: Any,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        content = str(getattr(response, "output_text", "") or "")
        tool_calls: list[dict[str, Any]] = []
        output_items: list[dict[str, Any]] = []
        for item in list(getattr(response, "output", None) or []):
            item_type = str(getattr(item, "type", "") or "")
            if item_type == "message":
                for block in list(getattr(item, "content", None) or []):
                    text = getattr(block, "text", None)
                    if text:
                        content += str(text) if not content else ""
                output_items.append({"type": "message", "role": "assistant", "content": content})
            elif item_type == "function_call":
                call = {
                    "id": str(getattr(item, "id", "") or ""),
                    "call_id": str(getattr(item, "call_id", "") or getattr(item, "id", "") or ""),
                    "name": str(getattr(item, "name", "") or ""),
                    "arguments": str(getattr(item, "arguments", "") or "{}"),
                    "type": "function_call",
                }
                tool_calls.append(call)
                output_items.append(call)
            elif item_type:
                output_items.append(
                    {
                        "type": item_type,
                        "raw": item.model_dump() if hasattr(item, "model_dump") else str(item),
                    }
                )
        return content, tool_calls, output_items

    async def _try_responses_complete(
        self, use_proxy: bool, messages: list[LLMMessage], **kwargs
    ) -> LLMResponse:
        import httpx
        from openai import AsyncOpenAI

        if not self.config.api_key:
            raise RuntimeError("openai_api_key_missing")
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
        params: dict[str, Any] = {
            "model": self.config.model,
            "input": self._response_input(messages),
            "max_output_tokens": kwargs.get(
                "max_output_tokens", kwargs.get("max_tokens", self.config.max_tokens)
            ),
            "store": bool(kwargs.get("store", False)),
        }
        if kwargs.get("tools"):
            params["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            params["tool_choice"] = kwargs["tool_choice"]
        if "parallel_tool_calls" in kwargs:
            params["parallel_tool_calls"] = bool(kwargs["parallel_tool_calls"])
        if kwargs.get("instructions"):
            params["instructions"] = kwargs["instructions"]
        if isinstance(kwargs.get("reasoning"), dict) and kwargs["reasoning"]:
            params["reasoning"] = kwargs["reasoning"]
        try:
            response = await client.responses.create(**params)
            content, tool_calls, output_items = self._parse_response_output(response)
            usage = getattr(response, "usage", None)
            return LLMResponse(
                content=content,
                model=str(getattr(response, "model", None) or self.config.model),
                prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                finish_reason="tool_call" if tool_calls else "stop",
                tool_calls=tool_calls,
                output_items=output_items,
                response_id=str(getattr(response, "id", "") or "") or None,
                raw={
                    "transport": "responses",
                    "response": response.model_dump() if hasattr(response, "model_dump") else {},
                },
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
                    if not _should_retry_without_proxy(proxy_exc):
                        raise
                    logger.warning(
                        "LLM call via proxy failed, retrying direct",
                        error=str(proxy_exc),
                        model=self.config.model,
                    )
                    resp = await self._try_complete(False, messages, **kwargs)
                latency = time.monotonic() - t0
                LLM_CALLS_TOTAL.labels(
                    provider=self.config.provider, model=self.config.model, status="ok"
                ).inc()
                LLM_LATENCY.labels(provider=self.config.provider, model=self.config.model).observe(
                    latency
                )
                return resp
            except Exception as exc:
                LLM_CALLS_TOTAL.labels(
                    provider=self.config.provider, model=self.config.model, status="error"
                ).inc()
                logger.error("LLM call failed", error=str(exc), model=self.config.model)
                raise

    async def stream(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[str]:
        if self._uses_responses_api:
            async for part in self._stream_responses(messages, **kwargs):
                yield part
            return

        async def _stream_once(use_proxy: bool):
            import httpx
            from openai import AsyncOpenAI

            if not self.config.api_key:
                raise RuntimeError("provider_api_key_missing")

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
                extra["extra_body"] = {"enable_thinking": self._qwen_thinking_enabled(kwargs)}
            optional = {
                "tools": self._chat_tools(kwargs.get("tools") or []),
                "tool_choice": kwargs.get("tool_choice"),
                "parallel_tool_calls": kwargs.get("parallel_tool_calls"),
            }
            extra.update(
                {k: v for k, v in optional.items() if v is not None and (k != "tools" or v)}
            )
            try:
                stream = await client.chat.completions.create(
                    model=self.config.model,
                    messages=oai_msgs,
                    temperature=kwargs.get("temperature", self.config.temperature),
                    max_tokens=kwargs.get(
                        "max_tokens", kwargs.get("max_output_tokens", self.config.max_tokens)
                    ),
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
            if not _should_retry_without_proxy(proxy_exc):
                raise
            logger.warning(
                "LLM stream via proxy failed, retrying direct",
                error=str(proxy_exc),
                model=self.config.model,
            )
            async for part in _stream_once(False):
                yield part

    async def _stream_responses(self, messages: list[LLMMessage], **kwargs) -> AsyncIterator[str]:
        import httpx
        from openai import AsyncOpenAI

        if not self.config.api_key:
            raise RuntimeError("openai_api_key_missing")
        timeout = httpx.Timeout(
            connect=min(15.0, float(self.config.timeout)),
            read=float(self.config.timeout),
            write=min(15.0, float(self.config.timeout)),
            pool=min(15.0, float(self.config.timeout)),
        )
        client_http = httpx.AsyncClient(trust_env=True, timeout=timeout)
        client = AsyncOpenAI(
            api_key=resolve_dashscope_api_key(self.config.api_key),
            base_url=self.config.base_url or None,
            timeout=timeout,
            http_client=client_http,
        )
        params: dict[str, Any] = {
            "model": self.config.model,
            "input": self._response_input(messages),
            "max_output_tokens": kwargs.get(
                "max_output_tokens", kwargs.get("max_tokens", self.config.max_tokens)
            ),
            "store": bool(kwargs.get("store", False)),
            "stream": True,
        }
        if kwargs.get("tools"):
            params["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            params["tool_choice"] = kwargs["tool_choice"]
        if "parallel_tool_calls" in kwargs:
            params["parallel_tool_calls"] = bool(kwargs["parallel_tool_calls"])
        try:
            stream = await client.responses.create(**params)
            async for event in stream:
                event_type = str(getattr(event, "type", "") or "")
                if event_type == "response.output_text.delta":
                    delta = str(getattr(event, "delta", "") or "")
                    if delta:
                        yield delta
        finally:
            await client_http.aclose()

    def _to_oai(self, m: LLMMessage) -> dict:
        content = self._chat_content(m.content)
        # DashScope Chat Completions uses the classic four roles; developer
        # instructions retain their priority by becoming system messages.
        role = "system" if m.role == "developer" else m.role
        msg: dict = {"role": role, "content": content}
        if m.name:
            msg["name"] = m.name
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            msg["tool_calls"] = m.tool_calls
        return msg

    @staticmethod
    def _qwen_thinking_enabled(kwargs: dict[str, Any]) -> bool:
        reasoning = kwargs.get("reasoning")
        effort = (str(reasoning.get("effort") or "") if isinstance(reasoning, dict) else "").lower()
        return effort in {"medium", "high", "xhigh"}

    @staticmethod
    def _chat_content(content: Any) -> Any:
        """Translate Responses-style multimodal parts for DashScope chat APIs."""
        if not isinstance(content, list):
            return content
        normalized: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                normalized.append({"type": "text", "text": str(part)})
                continue
            part_type = str(part.get("type") or "")
            if part_type in {"input_text", "output_text"}:
                normalized.append({"type": "text", "text": str(part.get("text") or "")})
            elif part_type == "input_image":
                image_url = part.get("image_url") or part.get("url")
                normalized.append(
                    {
                        "type": "image_url",
                        "image_url": (
                            image_url
                            if isinstance(image_url, dict)
                            else {"url": str(image_url or "")}
                        ),
                    }
                )
            elif part_type in {"input_audio", "audio_url"}:
                raw_audio = part.get("input_audio") or part.get("audio_url") or {}
                if isinstance(raw_audio, str):
                    raw_audio = {"data": raw_audio, "format": "wav"}
                normalized.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": str(raw_audio.get("data") or raw_audio.get("url") or ""),
                            "format": str(raw_audio.get("format") or "wav"),
                        },
                    }
                )
            elif part_type in {"input_video", "video_url"}:
                raw_video = part.get("video_url") or part.get("input_video") or {}
                if isinstance(raw_video, str):
                    raw_video = {"url": raw_video}
                video_part: dict[str, Any] = {
                    "type": "video_url",
                    "video_url": {"url": str(raw_video.get("url") or "")},
                }
                if part.get("fps") is not None:
                    video_part["fps"] = part["fps"]
                normalized.append(video_part)
            else:
                normalized.append(part)
        return normalized
