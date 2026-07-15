"""Retired v1 task API.

Scheduled work is now a first-class v2 resource and always runs through the
same durable Agent Loop as chat and goals.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse


router = APIRouter()


def _gone() -> JSONResponse:
    return JSONResponse(
        status_code=410,
        content={
            "code": "scheduled_task_api_retired",
            "message": "请迁移到 /api/v2/scheduled-tasks",
            "migration": "/api/v2/scheduled-tasks",
        },
    )


@router.get("/tasks", operation_id="retired_tasks_list", status_code=410)
async def retired_tasks_list() -> JSONResponse:
    return _gone()


@router.post("/tasks", operation_id="retired_tasks_create", status_code=410)
async def retired_tasks_create() -> JSONResponse:
    return _gone()


@router.get("/tasks/{path:path}", operation_id="retired_tasks_read", status_code=410)
async def retired_tasks_read(path: str) -> JSONResponse:
    del path
    return _gone()


@router.post("/tasks/{path:path}", operation_id="retired_tasks_action", status_code=410)
async def retired_tasks_action(path: str) -> JSONResponse:
    del path
    return _gone()
