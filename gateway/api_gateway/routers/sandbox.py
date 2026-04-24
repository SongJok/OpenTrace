"""
Session sandbox file download — 与 code_interpreter / file_sandbox 共用临时目录。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.api_gateway.routers.auth import get_current_user
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import ChatSession, User
from plugins.file.sandbox import resolve_readable_sandbox_file

router = APIRouter()


@router.get("/sandbox/download")
async def download_sandbox_file(
    session_id: str = Query(..., min_length=1, max_length=80),
    path: str = Query(..., min_length=1, max_length=512),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    r = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    if r.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Session not found or no permission")

    try:
        fp = resolve_readable_sandbox_file(session_id, path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None

    p = Path(fp)
    return FileResponse(
        path=p,
        filename=p.name,
        media_type="application/octet-stream",
    )
