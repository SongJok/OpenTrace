"""Model Context Protocol JSON-RPC 客户端，强制传输与工具治理策略。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


class MCPProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect_level: str = "read"


ApprovalCheck = Callable[[MCPTool, dict[str, Any]], Awaitable[bool]]
LedgerCheck = Callable[[str], Awaitable[dict[str, Any] | None]]
LedgerWrite = Callable[[str, dict[str, Any]], Awaitable[None]]


class MCPClient:
    def __init__(
        self,
        endpoint: str,
        *,
        bearer_token: str = "",
        allowed_tools: set[str] | None = None,
        timeout_seconds: float = 30,
        allow_insecure_localhost: bool = False,
    ) -> None:
        parsed = urlparse(endpoint)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (local and allow_insecure_localhost):
            raise ValueError("MCP endpoint 必须使用 HTTPS")
        self.endpoint = endpoint
        self.bearer_token = bearer_token
        self.allowed_tools = allowed_tools
        self.timeout_seconds = timeout_seconds

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        headers = {"content-type": "application/json"}
        if self.bearer_token:
            headers["authorization"] = f"Bearer {self.bearer_token}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.post(
                self.endpoint,
                headers=headers,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            )
        response.raise_for_status()
        payload = response.json()
        if payload.get("id") != request_id or payload.get("jsonrpc") != "2.0":
            raise MCPProtocolError("MCP 响应关联字段无效")
        if payload.get("error"):
            raise MCPProtocolError(str(payload["error"]))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise MCPProtocolError("MCP result 必须是对象")
        return result

    async def list_tools(self) -> list[MCPTool]:
        result = await self._rpc("tools/list", {})
        tools = []
        for item in result.get("tools") or []:
            name = str(item.get("name") or "")
            if not name or (self.allowed_tools is not None and name not in self.allowed_tools):
                continue
            annotations = dict(item.get("annotations") or {})
            tools.append(
                MCPTool(
                    name=name,
                    description=str(item.get("description") or ""),
                    input_schema=dict(item.get("inputSchema") or {}),
                    side_effect_level=str(annotations.get("sideEffectLevel") or "read"),
                )
            )
        return tools

    async def call_tool(
        self,
        tool: MCPTool,
        arguments: dict[str, Any],
        *,
        idempotency_key: str,
        approval_check: ApprovalCheck,
        ledger_check: LedgerCheck,
        ledger_write: LedgerWrite,
    ) -> dict[str, Any]:
        if self.allowed_tools is not None and tool.name not in self.allowed_tools:
            raise PermissionError("MCP 工具不在租户 allowlist")
        existing = await ledger_check(idempotency_key)
        if existing is not None:
            return existing
        if tool.side_effect_level in {"write", "destructive"}:
            if not await approval_check(tool, arguments):
                raise PermissionError("MCP 写工具缺少持久化审批")
        result = await self._rpc(
            "tools/call",
            {
                "name": tool.name,
                "arguments": arguments,
                "_meta": {"idempotencyKey": idempotency_key},
            },
        )
        await ledger_write(idempotency_key, result)
        return result
