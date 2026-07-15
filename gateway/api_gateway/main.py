from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.api_gateway.routers import (
    admin,
    agent_resources,
    analytical_skills,
    audit,
    auth,
    chat,
    cognitive,
    connectors,
    conversations,
    data,
    databases,
    documents,
    enterprise_admin,
    feedback,
    health,
    knowledge,
    memories,
    metrics,
    personalization,
    prometheus,
    response_aux,
    responses,
    rules,
    sandbox,
    skills,
    table_relationships,
    tasks,
    ui_settings,
)
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
from infra.observability.logger import get_logger
from infra.storage.database import ensure_runtime_schema

logger = get_logger(__name__)

app = FastAPI(title="OpenTrace API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from gateway.api_gateway.middleware.tenant import TenantContextMiddleware

    app.add_middleware(TenantContextMiddleware)
except Exception as exc:
    logger.warning("tenant_context_middleware_skipped", error=str(exc))


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    t0 = time.time()
    try:
        response = await call_next(request)
    except Exception:
        raise
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = str(int((time.time() - t0) * 1000))
    return response


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    payload: dict[str, Any] = {
        "code": exc.code,
        "message": exc.message,
        "details": exc.details,
        "request_id": request_id,
        "timestamp": int(time.time()),
    }
    return JSONResponse(status_code=exc.http_status, content=payload)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    spec = ErrorCodes.INTERNAL_ERROR
    payload = {
        "code": spec.code,
        "message": spec.message,
        "details": str(exc) if settings.debug and settings.app_env == "development" else None,
        "request_id": request_id,
        "timestamp": int(time.time()),
    }
    return JSONResponse(status_code=spec.http_status, content=payload)


@app.on_event("startup")
async def startup_event() -> None:
    from agents.bootstrap import register_builtin_agents

    register_builtin_agents()
    await ensure_runtime_schema()


app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(prometheus.router, prefix="/api/v1", tags=["observability"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(responses.router, prefix="/api/v2", tags=["responses"])
app.include_router(response_aux.router, prefix="/api/v2", tags=["response-resources"])
app.include_router(agent_resources.router, prefix="/api/v2", tags=["agent-resources"])
app.include_router(conversations.router, prefix="/api/v2", tags=["conversations-v2"])
app.include_router(memories.router, prefix="/api/v2", tags=["memories-v2"])
app.include_router(personalization.router, prefix="/api/v2", tags=["personalization-v2"])
app.include_router(personalization.router, prefix="/api/v1", tags=["personalization"])
app.include_router(conversations.router, prefix="/api/v1", tags=["conversations"])
app.include_router(cognitive.router, prefix="/api/v1", tags=["cognitive"])
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
app.include_router(knowledge.router, prefix="/api/v1", tags=["knowledge"])
app.include_router(memories.router, prefix="/api/v1", tags=["memories"])
app.include_router(tasks.router, prefix="/api/v1", tags=["tasks"])
app.include_router(audit.router, prefix="/api/v1", tags=["audit"])
app.include_router(connectors.router, prefix="/api/v1", tags=["connectors"])
app.include_router(skills.router, prefix="/api/v1", tags=["skills"])
app.include_router(ui_settings.router, prefix="/api/v1", tags=["ui_settings"])
app.include_router(data.router, prefix="/api/v1", tags=["data"])
app.include_router(databases.router, prefix="/api/v1", tags=["databases"])
app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
app.include_router(sandbox.router, prefix="/api/v1", tags=["sandbox"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(enterprise_admin.router, prefix="/api/v1", tags=["enterprise-admin"])
app.include_router(rules.router, prefix="/api/v1", tags=["rules"])
app.include_router(metrics.router, prefix="/api/v1", tags=["metrics"])
app.include_router(table_relationships.router, prefix="/api/v1", tags=["table-relationships"])
app.include_router(analytical_skills.router, prefix="/api/v1", tags=["analytical-skills"])
