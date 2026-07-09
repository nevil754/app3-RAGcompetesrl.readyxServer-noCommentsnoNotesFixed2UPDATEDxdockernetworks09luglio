from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from app.core.settings import get_settings

settings = get_settings()

EXCLUDED_PATHS = { "/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json" }

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = getattr(request.state, "user_id", None)
        if not tenant_id or not user_id:
            return await call_next(request)
        try:
            from app.core.redis_client import TenantRedis
            redis = TenantRedis(tenant_id=tenant_id)
            allowed, count = await redis.check_rate_limit(
                user_id=user_id,
                limit=settings.rate_limit_requests_per_minute,
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Rate limit superato",
                        "detail": f"Max {settings.rate_limit_requests_per_minute} richieste/minuto",
                        "retry_after": 60,
                    },
                    headers={"Retry-After": "60"},
                )
        except Exception:

            pass
        return await call_next(request)

