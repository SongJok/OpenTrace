"""
OpenTrace Python SDK — async client with streaming support.
"""
from __future__ import annotations

import uuid
from typing import AsyncIterator, Optional

import httpx


class OpenTraceClient:
    """
    Async Python SDK for the OpenTrace API.

    Usage::

        async with OpenTraceClient() as client:
            # Standard chat
            resp = await client.chat("Explain quantum entanglement")
            print(resp["content"])

            # Streaming chat
            async for chunk in client.stream("Tell me a story"):
                print(chunk, end="", flush=True)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:14100",
        timeout: float = 120.0,
        api_key: Optional[str] = None,
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
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Send a query and get a complete response."""
        payload = {
            "query": query,
            "session_id": session_id or str(uuid.uuid4()),
            "user_id": user_id or "",
            "stream": False,
        }
        resp = await self._client.post("/api/v1/chat", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def stream(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream response chunks via SSE.
        Yields delta text strings as they arrive.
        """
        import json as _json
        sid = session_id or str(uuid.uuid4())
        payload = {
            "query": query,
            "session_id": sid,
            "user_id": user_id or "",
            "stream": True,
        }
        async with self._client.stream(
            "POST", "/api/v1/chat", json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if not raw:
                    continue
                try:
                    event = _json.loads(raw)
                except _json.JSONDecodeError:
                    continue
                if event.get("error"):
                    raise RuntimeError(event["error"])
                delta = event.get("delta", "")
                if delta:
                    yield delta
                if event.get("done"):
                    break

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    async def get_session(self, session_id: str) -> dict:
        """Retrieve session history and metadata."""
        resp = await self._client.get(f"/api/v1/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def delete_session(self, session_id: str) -> dict:
        """Delete a session."""
        resp = await self._client.delete(f"/api/v1/sessions/{session_id}")
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
        score: Optional[float] = None,
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

    async def __aenter__(self) -> "OpenTraceClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()
