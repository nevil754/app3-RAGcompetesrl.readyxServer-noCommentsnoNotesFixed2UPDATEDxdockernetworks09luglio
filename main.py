from __future__ import annotations
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from app.core.observability import setup_all
from app.core.settings import get_settings

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(f"Avvio {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment {settings.app_environment}")
    setup_all(settings)
    await _check_services()
    if settings.app_environment != "development":
        await _preload_models()
    logger.info("Startup completato, app pronta")
    yield
    logger.info("Shutdown in corso...")
    try:
        from app.db.sqlserver import get_async_engine
        await get_async_engine().dispose()
        logger.info("Engine SQL Server chiuso")
    except Exception as e:
        logger.warning(f"Errore chiusura engine: {e}")
    try:
        from app.core.redis_client import get_redis, get_cache_redis
        await get_redis().aclose()
        await get_cache_redis().aclose()
        logger.info("Connessioni Redis chiuse")
    except Exception as e:
        logger.warning(f"Errore chiusura Redis: {e}")
    logger.info("Shutdown completato")

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
        docs_url="/docs" if settings.app_debug else None,
        redoc_url="/redoc" if settings.app_debug else None,
        openapi_url="/openapi.json" if settings.app_debug else None,

        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_debug else ["https://FRONTEND-OR-BACKENDASPNETCORE"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.middleware.logging import LoggingMiddleware
    app.add_middleware(LoggingMiddleware)
    from app.api.middleware.tenant import TenantMiddleware
    app.add_middleware(TenantMiddleware)
    from app.api.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
    from app.api.routes.health import router as health_router
    from app.api.routes.auth import router as auth_router
    app.include_router(health_router)
    app.include_router(auth_router, prefix="/api/v1")

    from app.api.routes.chat import router as chat_router
    app.include_router(chat_router, prefix="/api/v1")

    from app.api.routes.collections import router as collections_router
    app.include_router(collections_router, prefix="/api/v1")

    from app.api.routes.documents import router as documents_router
    app.include_router(documents_router, prefix="/api/v1")

    from app.api.routes.tenants import router as tenants_router
    app.include_router(tenants_router, prefix="/api/v1")

    from app.api.routes.users import router as users_router
    app.include_router(users_router, prefix="/api/v1")

    from app.api.routes.jobs import router as jobs_router
    app.include_router(jobs_router, prefix="/api/v1")

    return app

async def _check_services() -> None:
    from app.core.redis_client import TenantRedis
    from app.db.sqlserver import TenantDB
    from app.core.vectorstore import get_async_qdrant_client
    redis_ok = await TenantRedis.ping()
    if not redis_ok:
        logger.warning("Redis non raggiungibile all'avvio — retry automatici in corso")
    else:
        logger.info("Redis: connesso!")
    sql_ok = await TenantDB.ping()
    if not sql_ok:
        logger.warning("SQL Server non raggiungibile all'avvio")
    else:
        logger.info("SQL Server: connesso!")
    try:
        client = get_async_qdrant_client()
        await client.get_collections()
        logger.info("Qdrant: connesso")
    except Exception as e:
        logger.warning(f"Qdrant non raggiungibile all'avvio: {e}")

async def _preload_models() -> None:
    try:
        import asyncio
        from app.core.embeddings import get_embedding_model, get_reranker_model
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, get_embedding_model)
        logger.info("Modello embedding pre-caricato")
        from app.core.settings import get_settings
        if get_settings().reranker_enabled:
            await loop.run_in_executor(None, get_reranker_model)
            logger.info("Reranker pre-caricato")
    except Exception as e:
        logger.warning(f"Pre-caricamento modelli fallito: {e}")

app = create_app()

