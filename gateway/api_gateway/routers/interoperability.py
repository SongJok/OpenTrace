"""MCP Server 与 A2A 入口；所有任务都转换为 durable Response。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.routers.responses import ResponseCreateRequest, create_response
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User
from kernel.interoperability.a2a import A2AMessage, A2ASigner

router = APIRouter()


class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field(pattern=r"^2\.0$")
    id: str | int
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class A2ATaskRequest(BaseModel):
    message: A2AMessage
    input: str
    conversation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _rpc_result(request: JsonRpcRequest, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request.id, "result": result}


def _require_enabled(flag: bool, protocol: str) -> None:
    if not flag:
        raise AppException(ErrorCodes.RESOURCE_NOT_FOUND.code, message=f"{protocol} 未启用")


@router.post("/mcp")
async def mcp_server(
    rpc: JsonRpcRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_enabled(settings.mcp_server_enabled, "MCP Server")
    if rpc.method == "initialize":
        return _rpc_result(
            rpc,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "opentrace", "version": "0.1.0"},
            },
        )
    if rpc.method == "tools/list":
        return _rpc_result(
            rpc,
            {
                "tools": [
                    {
                        "name": "opentrace.respond",
                        "description": "通过 OpenTrace durable Responses 主路径执行 Agent 任务",
                        "inputSchema": {
                            "type": "object",
                            "required": ["input"],
                            "properties": {
                                "input": {"type": "string"},
                                "conversation": {"type": "string"},
                                "metadata": {"type": "object"},
                            },
                        },
                        "annotations": {"sideEffectLevel": "write", "durable": True},
                    }
                ]
            },
        )
    if rpc.method == "tools/call":
        if str(rpc.params.get("name") or "") != "opentrace.respond":
            raise AppException(ErrorCodes.PARAM_INVALID.code, message="未知 MCP 工具")
        arguments = dict(rpc.params.get("arguments") or {})
        response_request = ResponseCreateRequest(
            input=str(arguments.get("input") or ""),
            conversation=arguments.get("conversation"),
            background=True,
            metadata=dict(arguments.get("metadata") or {}),
        )
        meta = dict(rpc.params.get("_meta") or {})
        durable = await create_response(
            http_request,
            response_request,
            str(meta.get("idempotencyKey") or "") or None,
            current_user,
            db,
        )
        return _rpc_result(
            rpc, {"content": [{"type": "text", "text": str(durable)}], "durableResponse": durable}
        )
    raise AppException(ErrorCodes.PARAM_INVALID.code, message="不支持的 MCP 方法")


@router.get("/.well-known/agent-card.json")
async def a2a_agent_card() -> dict[str, Any]:
    _require_enabled(settings.a2a_protocol_enabled, "A2A")
    return {
        "name": "OpenTrace",
        "description": "Governed durable AgentOS",
        "url": "/api/v2/a2a/tasks/send",
        "version": "0.1.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
        "authentication": {"schemes": ["bearer", "hmac"]},
    }


@router.post("/a2a/tasks/send")
async def send_a2a_task(
    request: A2ATaskRequest,
    http_request: Request,
    signature: str = Header(alias="X-A2A-Signature"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_enabled(settings.a2a_protocol_enabled, "A2A")
    signer = A2ASigner(settings.a2a_service_secret)
    if not signer.verify(request.message, signature):
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message="A2A 服务身份签名无效")
    durable = await create_response(
        http_request,
        ResponseCreateRequest(
            input=request.input,
            conversation=request.conversation,
            background=True,
            metadata={
                **request.metadata,
                "a2a": {"task_id": request.message.task_id, "sender": request.message.sender},
            },
        ),
        request.message.message_id,
        current_user,
        db,
    )
    return {"task_id": request.message.task_id, "response": durable}
