from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.security import decode_access_token, extract_bearer_token

class TenantMiddleware(BaseHTTPMiddleware):

    PUBLIC_PATHS = {"/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next) -> Response:

        request.state.tenant_id = None
        request.state.tenant_slug = None
        request.state.user_id = None
        request.state.user_role = None
        if request.url.path in self.PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        token = extract_bearer_token(auth_header)
        if token:
            payload = decode_access_token(token)
            if payload:

                request.state.tenant_id = payload.get("tenant_id")
                request.state.tenant_slug = payload.get("tenant_slug")
                request.state.user_id = payload.get("sub")
                request.state.user_role = payload.get("role")
        return await call_next(request)

