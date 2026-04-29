from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.api_gateway.routers import (
    admin,
    audit,
    auth,
    chat,
    cognitive,
    connectors,
    conversations,
    data,
    databases,
    documents,
    feedback,
    health,
    memories,
    rules,
    sandbox,
    skills,
    tasks,
    ui_settings,
)
from infra.message_bus.subscribers import memory_event_subscriber
from infra.errors import AppException, ErrorCodes


app = FastAPI(title="OpenTrace API", version="0.1.0")
_subscriber_task: asyncio.Task | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        "details": str(exc),
        "request_id": request_id,
        "timestamp": int(time.time()),
    }
    return JSONResponse(status_code=spec.http_status, content=payload)


@app.on_event("startup")
async def startup_event() -> None:
    global _subscriber_task
    if _subscriber_task is None or _subscriber_task.done():
        _subscriber_task = asyncio.create_task(memory_event_subscriber.start())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _subscriber_task
    try:
        await memory_event_subscriber.stop()
    finally:
        if _subscriber_task and not _subscriber_task.done():
            _subscriber_task.cancel()
            with contextlib.suppress(Exception):
                await _subscriber_task
        _subscriber_task = None


app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(conversations.router, prefix="/api/v1", tags=["conversations"])
app.include_router(cognitive.router, prefix="/api/v1", tags=["cognitive"])
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
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
app.include_router(rules.router, prefix="/api/v1", tags=["rules"])
