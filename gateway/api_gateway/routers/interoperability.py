"""MCP Server 与 A2A 入口；所有任务都转换为 durable Response。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.resource_scope import get_accessible_data_source
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.routers.responses import ResponseCreateRequest, create_response
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User
from kernel.interoperability.a2a import A2AMessage, A2ASigner
from text2sql.adapters.opentrace.evidence import OpenTraceEvidenceProvider
from text2sql.contracts import ExecutionMode, QueryRequest
from text2sql.mcp import mcp_tools
from text2sql.research import ResearchPlanner

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
        tools = [
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
        if settings.text2sql_enabled:
            tools.extend(mcp_tools())
        return _rpc_result(
            rpc,
            {"tools": tools},
        )
    if rpc.method == "tools/call":
        tool_name = str(rpc.params.get("name") or "")
        if tool_name.startswith("text2sql."):
            _require_enabled(settings.text2sql_enabled, "Text2SQL")
        if tool_name == "text2sql.query":
            arguments = dict(rpc.params.get("arguments") or {})
            data_source_id = str(arguments.get("data_source_id") or "").strip()
            question = str(arguments.get("question") or "").strip()
            if not data_source_id or not question:
                raise AppException(
                    ErrorCodes.PARAM_INVALID.code,
                    message="Text2SQL MCP 缺少 question 或 data_source_id",
                )
            from gateway.api_gateway.routers.text2sql import (
                _scope,
                _service,
                _validate_max_rows,
                _validate_project_scope,
            )

            project_id = arguments.get("project_id")
            scope = _scope(http_request, current_user, data_source_id, project_id)
            await _validate_project_scope(db, scope=scope, project_id=project_id)
            try:
                _validate_max_rows(int(arguments.get("max_rows") or 100))
            except (TypeError, ValueError) as exc:
                raise AppException(
                    ErrorCodes.PARAM_INVALID.code, message="Text2SQL MCP max_rows 无效"
                ) from exc
            source = await get_accessible_data_source(
                db,
                user_id=current_user.id,
                tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
                data_source_id=data_source_id,
                required_permission="query",
                active_only=True,
            )
            if source is None:
                raise AppException(
                    ErrorCodes.RESOURCE_NOT_FOUND.code, message="data source not found"
                )
            mode = str(arguments.get("mode") or "sql_only")
            if mode not in {"sql_only", "execute_and_answer"}:
                raise AppException(ErrorCodes.PARAM_INVALID.code, message="Text2SQL MCP mode 无效")
            run = await _service(db, source).create(
                QueryRequest(
                    question=question,
                    scope=scope,
                    mode=ExecutionMode(mode),
                    confirmed=bool(arguments.get("confirmed", False)),
                    max_rows=int(arguments.get("max_rows") or 100),
                    idempotency_key=(str(arguments.get("idempotency_key") or "").strip() or None),
                )
            )
            return _rpc_result(
                rpc,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(run.model_dump(mode="json"), ensure_ascii=False),
                        }
                    ]
                },
            )
        if tool_name == "text2sql.catalog":
            arguments = dict(rpc.params.get("arguments") or {})
            data_source_id = str(arguments.get("data_source_id") or "").strip()
            if not data_source_id:
                raise AppException(
                    ErrorCodes.PARAM_INVALID.code,
                    message="Text2SQL MCP 缺少 data_source_id",
                )
            from gateway.api_gateway.routers.text2sql import (
                _scope,
                _validate_project_scope,
            )

            project_id = arguments.get("project_id")
            scope = _scope(http_request, current_user, data_source_id, project_id)
            await _validate_project_scope(db, scope=scope, project_id=project_id)
            source = await get_accessible_data_source(
                db,
                user_id=current_user.id,
                tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
                data_source_id=data_source_id,
                required_permission="view",
                active_only=True,
            )
            if source is None:
                raise AppException(
                    ErrorCodes.RESOURCE_NOT_FOUND.code, message="data source not found"
                )
            evidence = await OpenTraceEvidenceProvider(db, source).collect(
                scope,
                str(arguments.get("question") or ""),
                ResearchPlanner().plan(str(arguments.get("question") or "")),
            )
            return _rpc_result(
                rpc,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                evidence.model_dump(mode="json"), ensure_ascii=False
                            ),
                        }
                    ]
                },
            )
        if tool_name == "text2sql.feedback":
            arguments = dict(rpc.params.get("arguments") or {})
            data_source_id = str(arguments.get("data_source_id") or "").strip()
            run_id = str(arguments.get("run_id") or "").strip()
            if not data_source_id or not run_id:
                raise AppException(
                    ErrorCodes.PARAM_INVALID.code,
                    message="Text2SQL MCP 缺少 run_id 或 data_source_id",
                )
            from gateway.api_gateway.routers.text2sql import (
                FeedbackRequest,
                _scope,
                _validate_project_scope,
            )
            from infra.storage.text2sql_models import Text2SQLFeedback
            from text2sql.adapters.opentrace.repository import OpenTraceRunRepository

            project_id = arguments.get("project_id")
            scope = _scope(http_request, current_user, data_source_id, project_id)
            await _validate_project_scope(db, scope=scope, project_id=project_id)
            source = await get_accessible_data_source(
                db,
                user_id=current_user.id,
                tenant_metadata={"tenant_id": scope.tenant_id, "workspace_id": scope.workspace_id},
                data_source_id=data_source_id,
                required_permission="view",
                active_only=True,
            )
            if source is None:
                raise AppException(
                    ErrorCodes.RESOURCE_NOT_FOUND.code, message="data source not found"
                )
            run = await OpenTraceRunRepository(db).get(run_id, scope)
            if run is None:
                raise AppException(
                    ErrorCodes.RESOURCE_NOT_FOUND.code, message="text2sql run not found"
                )
            feedback = FeedbackRequest.model_validate(arguments)
            record = Text2SQLFeedback(
                run_id=run_id,
                user_id=current_user.id,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                verdict=feedback.verdict,
                candidate_id=feedback.candidate_id,
                corrected_sql=feedback.corrected_sql,
                comment=feedback.comment,
                metadata_json=feedback.metadata,
            )
            db.add(record)
            await db.commit()
            return _rpc_result(
                rpc,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"feedback_id": record.id, "stored": True, "promoted": False},
                                ensure_ascii=False,
                            ),
                        }
                    ]
                },
            )
        if tool_name != "opentrace.respond":
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
