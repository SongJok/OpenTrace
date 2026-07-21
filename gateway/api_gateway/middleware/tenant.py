"""FastAPI middleware — attach tenant headers to request.state."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Authentication happens inside route dependencies. Tenant headers are
        # therefore validated there, where the signature can be bound to user_id.
        request.state.tenant_metadata = {
            "tenant_id": "default",
            "org_id": "default",
            "workspace_id": "default",
        }
        return await call_next(request)
