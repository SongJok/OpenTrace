"""Migration tombstone for the retired v1 chat execution surface."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse


router = APIRouter()


def _gone() -> JSONResponse:
    return JSONResponse(
        status_code=410,
        content={
            "code": "chat_endpoint_retired",
            "message": "旧 Chat API 已停止执行，请迁移到 /api/v2/responses。",
            "migration": "/api/v2/responses",
        },
    )


@router.post("/chat", operation_id="retired_chat", status_code=410)
async def retired_chat() -> JSONResponse:
    return _gone()


@router.post("/chat/{path:path}", operation_id="retired_chat_action", status_code=410)
async def retired_chat_action(path: str) -> JSONResponse:
    del path
    return _gone()


@router.get("/chat/{path:path}", operation_id="retired_chat_read", status_code=410)
async def retired_chat_read(path: str) -> JSONResponse:
    del path
    return _gone()
