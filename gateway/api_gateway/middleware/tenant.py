"""FastAPI middleware — attach tenant headers to request.state."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from gateway.api_gateway.tenant_middleware import build_tenant_metadata


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            request.state.tenant_metadata = build_tenant_metadata(request, user_id=None)
        except Exception:
            request.state.tenant_metadata = {"tenant_id": "default"}
        return await call_next(request)