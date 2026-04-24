from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any, Dict

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="")
session_id_ctx: ContextVar[str] = ContextVar("session_id", default="")


def ensure_request_context(request_id: str = "", trace_id: str = "") -> tuple[str, str]:
    rid = request_id or str(uuid.uuid4())
    tid = trace_id or str(uuid.uuid4())
    request_id_ctx.set(rid)
    trace_id_ctx.set(tid)
    return rid, tid


def set_user_session_context(user_id: str = "", session_id: str = "") -> None:
    if user_id:
        user_id_ctx.set(user_id)
    if session_id:
        session_id_ctx.set(session_id)


def clear_request_context() -> None:
    request_id_ctx.set("")
    trace_id_ctx.set("")
    user_id_ctx.set("")
    session_id_ctx.set("")


def get_log_context() -> Dict[str, Any]:
    return {
        "request_id": request_id_ctx.get(),
        "trace_id": trace_id_ctx.get(),
        "user_id": user_id_ctx.get(),
        "session_id": session_id_ctx.get(),
    }
