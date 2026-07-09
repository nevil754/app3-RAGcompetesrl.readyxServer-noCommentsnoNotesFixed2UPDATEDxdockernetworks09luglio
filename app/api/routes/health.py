from __future__ import annotations
import time
from typing import Any
from fastapi import APIRouter
from loguru import logger
from app.core.settings import get_settings

router = APIRouter(tags=["health"])
settings = get_settings()
_start_time = time.time()

@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_environment,
        "uptime_seconds": round(time.time() - _start_time),
    }

@router.get("/ready")
async def ready() -> dict[str, Any]:
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    checks: dict[str, Any] = {}
    all_ok = True
    try:
        from app.core.redis_client import TenantRedis
        redis_ok = await TenantRedis.ping()
        checks["redis"] = "ok" if redis_ok else "error"
        if not redis_ok:
            all_ok = False
    except Exception as e:
        checks["redis"] = f"error: {e}"
        all_ok = False
    try:
        from app.db.sqlserver import TenantDB
        sql_ok = await TenantDB.ping()
        checks["sqlserver"] = "ok" if sql_ok else "error"
        if not sql_ok:
            all_ok = False
    except Exception as e:
        checks["sqlserver"] = f"error: {e}"
        all_ok = False
    try:
        from app.core.vectorstore import get_async_qdrant_client
        client = get_async_qdrant_client()
        info = await client.get_collections()
        checks["qdrant"] = "ok"
    except Exception as e:
        checks["qdrant"] = f"error: {e}"
        all_ok = False
    result = {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
        "uptime_seconds": round(time.time() - _start_time),
    }
    if not all_ok:
        logger.warning("Readiness check fallito", checks=checks)
        return JSONResponse(status_code=503, content=result)
    return result

