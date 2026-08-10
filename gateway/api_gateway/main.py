from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from gateway.api_gateway.routers import (
    admin,
    agent_resources,
    alerts,
    analytical_skills,
    audit,
    auth,
    calendar,
    chat,
    cognitive,
    company_brain,
    connectors,
    conversations,
    data,
    data_governance,
    databases,
    documents,
    enterprise_admin,
    enterprise_context,
    enterprise_reports,
    feedback,
    health,
    interoperability,
    knowledge,
    knowledge_enterprise,
    memories,
    metrics,
    personalization,
    prometheus,
    resource_permissions,
    response_aux,
    responses,
    rules,
    sandbox,
    schema_annotations,
    skills,
    sql_assets,
    table_relationships,
    tasks,
    text2sql,
    ui_settings,
    workbench,
)
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
from infra.observability.logger import get_logger
from infra.observability.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL
from infra.observability.tracer import setup_tracing
from infra.storage.database import ensure_runtime_schema

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from agents.bootstrap import register_builtin_agents

    register_builtin_agents()
    if settings.trace_enabled:
        setup_tracing(
            service_name=settings.otel_service_name,
            otlp_endpoint=settings.otel_exporter_otlp_endpoint,
            enabled=True,
        )
    await ensure_runtime_schema()
    yield


app = FastAPI(title="OpenTrace API", version="0.1.0", lifespan=lifespan)


def _error_payload(request: Request, *, code: int, message: str, details: Any) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": jsonable_encoder(details),
        "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
        "timestamp": int(time.time()),
    }


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
    t0 = time.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    finally:
        route = request.scope.get("route")
        endpoint = str(getattr(route, "path", "__unmatched__"))
        duration = max(0.0, time.monotonic() - t0)
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            endpoint=endpoint,
            status=str(status_code),
        ).inc()
        HTTP_REQUEST_DURATION.labels(method=request.method, endpoint=endpoint).observe(duration)
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = str(int(duration * 1000))
    return response


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    payload = _error_payload(
        request,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )
    return JSONResponse(status_code=exc.http_status, content=payload)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    spec = ErrorCodes.PARAM_INVALID
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            request,
            code=spec.code,
            message=spec.message,
            details=exc.errors(),
        ),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    spec = {
        403: ErrorCodes.PERMISSION_DENIED,
        404: ErrorCodes.RESOURCE_NOT_FOUND,
        409: ErrorCodes.RESOURCE_EXISTS,
    }.get(exc.status_code, ErrorCodes.PARAM_INVALID)
    message = exc.detail if isinstance(exc.detail, str) else spec.message
    details = None if isinstance(exc.detail, str) else exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(request, code=spec.code, message=message, details=details),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    spec = ErrorCodes.INTERNAL_ERROR
    payload = _error_payload(
        request,
        code=spec.code,
        message=spec.message,
        details=str(exc) if settings.debug and settings.app_env == "development" else None,
    )
    return JSONResponse(status_code=spec.http_status, content=payload)


app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(prometheus.router, prefix="/api/v1", tags=["observability"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(data_governance.router, prefix="/api/v1", tags=["data-governance"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(responses.router, prefix="/api/v2", tags=["responses"])
app.include_router(interoperability.router, prefix="/api/v2", tags=["interoperability"])
app.include_router(response_aux.router, prefix="/api/v2", tags=["response-resources"])
app.include_router(agent_resources.router, prefix="/api/v2", tags=["agent-resources"])
app.include_router(calendar.router, prefix="/api/v2", tags=["calendar"])
app.include_router(company_brain.router, prefix="/api/v2", tags=["company-brain"])
app.include_router(workbench.router, prefix="/api/v2", tags=["enterprise-workbench"])
app.include_router(enterprise_context.router, prefix="/api/v2", tags=["enterprise-context"])
app.include_router(enterprise_reports.router, prefix="/api/v2", tags=["enterprise-reports"])
app.include_router(alerts.router, prefix="/api/v2", tags=["alerts"])
app.include_router(resource_permissions.router, prefix="/api/v2", tags=["resource-permissions"])
app.include_router(conversations.router, prefix="/api/v2", tags=["conversations-v2"])
app.include_router(memories.router, prefix="/api/v2", tags=["memories-v2"])
app.include_router(personalization.router, prefix="/api/v2", tags=["personalization-v2"])
app.include_router(personalization.router, prefix="/api/v1", tags=["personalization"])
app.include_router(conversations.router, prefix="/api/v1", tags=["conversations"])
app.include_router(cognitive.router, prefix="/api/v1", tags=["cognitive"])
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
app.include_router(knowledge.router, prefix="/api/v1", tags=["knowledge"])
app.include_router(knowledge_enterprise.router, prefix="/api/v1", tags=["enterprise-knowledge"])
app.include_router(memories.router, prefix="/api/v1", tags=["memories"])
app.include_router(tasks.router, prefix="/api/v1", tags=["tasks"])
app.include_router(audit.router, prefix="/api/v1", tags=["audit"])
app.include_router(connectors.router, prefix="/api/v1", tags=["connectors"])
app.include_router(skills.router, prefix="/api/v1", tags=["skills"])
app.include_router(ui_settings.router, prefix="/api/v1", tags=["ui_settings"])
app.include_router(data.router, prefix="/api/v1", tags=["data"])
app.include_router(text2sql.router, prefix="/api/v1", tags=["text2sql"])
app.include_router(databases.router, prefix="/api/v1", tags=["databases"])
app.include_router(schema_annotations.router, prefix="/api/v1", tags=["schema-annotations"])
app.include_router(sql_assets.router, prefix="/api/v1", tags=["sql-assets"])
app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
app.include_router(sandbox.router, prefix="/api/v1", tags=["sandbox"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(enterprise_admin.router, prefix="/api/v1", tags=["enterprise-admin"])
app.include_router(rules.router, prefix="/api/v1", tags=["rules"])
app.include_router(metrics.router, prefix="/api/v1", tags=["metrics"])
app.include_router(table_relationships.router, prefix="/api/v1", tags=["table-relationships"])
app.include_router(analytical_skills.router, prefix="/api/v1", tags=["analytical-skills"])
