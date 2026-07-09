from __future__ import annotations

import time
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class LoggingMiddleware(BaseHTTPMiddleware):

    SKIP_PATHS = {"/health", "/ready", "/metrics"}

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)
        start = time.perf_counter()
        with logger.contextualize(
            request_id=request_id,
            tenant_id=getattr(request.state, "tenant_id", None),
            user_id=getattr(request.state, "user_id", None),
        ):
            logger.info(
                f"→ {request.method} {request.url.path}",
                method=request.method,
                path=request.url.path,
                client=request.client.host if request.client else None,
            )
            try:
                response = await call_next(request)
            except Exception as e:
                duration_ms = round((time.perf_counter() - start) * 1000)
                logger.error(
                    f"✗ {request.method} {request.url.path} — eccezione non gestita",
                    error=str(e),
                    duration_ms=duration_ms,
                )
                raise
            duration_ms = round((time.perf_counter() - start) * 1000)
            level = "info" if response.status_code < 400 else "warning"
            if response.status_code >= 500:
                level = "error"
            logger.log(
                level.upper(),
                f"← {response.status_code} {request.method} {request.url.path} [{duration_ms}ms]",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        response.headers["X-Request-ID"] = request_id
        return response

