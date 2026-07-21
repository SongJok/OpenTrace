"""
OpenTrace Python SDK — async client with streaming support.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx


class OpenTraceClient:
    """
    Async Python SDK for the OpenTrace API.

    Usage::

        async with OpenTraceClient() as client:
            # Standard chat
            resp = await client.chat("Explain quantum entanglement")
            print(resp["output_text"])

            # Streaming chat
            async for chunk in client.stream("Tell me a story"):
                print(chunk, end="", flush=True)
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:14100",
        timeout: float = 120.0,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    async def chat(
        self,
        query: str,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        """通过持久化 Responses 主链路发送查询并等待完整结果。"""
        del user_id  # 用户身份只从 Bearer token 获取，禁止由调用方覆盖。
        payload = {"input": query, "stream": False}
        if session_id:
            payload["conversation"] = session_id
        resp = await self._client.post("/api/v2/responses", json=payload)
        resp.raise_for_status()
        result = resp.json()
        # 保留旧 SDK 的便捷字段，执行协议与事实来源仍完全来自 Responses。
        result.setdefault("content", result.get("output_text") or "")
        conversation = result.get("conversation") or {}
        result.setdefault(
            "session_id", conversation.get("id") if isinstance(conversation, dict) else conversation
        )
        return result

    async def stream(
        self,
        query: str,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream response chunks via SSE.
        Yields delta text strings as they arrive.
        """
        del user_id
        payload = {"input": query, "stream": True}
        if session_id:
            payload["conversation"] = session_id
        async with self._client.stream("POST", "/api/v2/responses", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:") :].strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event_type = str(event.get("type") or "")
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                if event_type == "response.failed":
                    raise RuntimeError(
                        str(data.get("message") or data.get("error") or "response failed")
                    )
                delta = data.get("delta", "") if event_type == "response.output_text.delta" else ""
                if delta:
                    yield str(delta)
                if event_type in {
                    "response.completed",
                    "response.failed",
                    "response.cancelled",
                    "response.requires_action",
                }:
                    break

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    async def get_session(self, session_id: str) -> dict:
        """读取当前 Responses 分支投影出的会话历史。"""
        resp = await self._client.get(f"/api/v2/conversations/{session_id}/messages")
        resp.raise_for_status()
        return {"id": session_id, "messages": resp.json()}

    async def delete_session(self, session_id: str) -> dict:
        """Delete a session."""
        resp = await self._client.delete(f"/api/v2/conversations/{session_id}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------
    async def feedback(
        self,
        session_id: str,
        query: str,
        response: str,
        feedback_type: str = "thumbs_up",
        score: float | None = None,
    ) -> dict:
        payload = {
            "session_id": session_id,
            "query": query,
            "response": response,
            "feedback_type": feedback_type,
            "score": score,
        }
        resp = await self._client.post("/api/v1/feedback", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Health / admin
    # ------------------------------------------------------------------
    async def health(self) -> dict:
        resp = await self._client.get("/api/v1/health")
        resp.raise_for_status()
        return resp.json()

    async def list_tools(self) -> list[str]:
        resp = await self._client.get("/api/v1/admin/tools")
        resp.raise_for_status()
        return resp.json().get("tools", [])

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OpenTraceClient:
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()
