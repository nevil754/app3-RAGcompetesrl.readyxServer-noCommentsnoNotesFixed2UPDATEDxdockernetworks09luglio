from __future__ import annotations
import sys
import os
from typing import TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from app.core.settings import AppSettings

def setup_all(settings: "AppSettings") -> None:
    setup_logging(settings)
    setup_langsmith(settings)
    setup_opentelemetry(settings)

def setup_logging(settings: "AppSettings") -> None:
    logger.remove()
    level = settings.log_level.upper()
    if settings.log_json_output:

        logger.add(
            sys.stdout,
            level=level,
            format="{time:YYYY-MM-DDTHH:mm:ss.SSSZ} {level} {name}:{line} {message} {extra}",
            serialize=True,
            backtrace=False,
            diagnose=False,
        )
    else:
        fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )
        if settings.log_colored:
            logger.add(sys.stdout, level=level, format=fmt, colorize=True)
        else:
            logger.add(sys.stdout, level=level, format=fmt, colorize=False)

    _intercept_stdlib_logging()
    logger.info(
        "Logging configurato",
        level=level,
        json=settings.log_json_output,
        env=settings.app_environment,
    )

def setup_langsmith(settings: "AppSettings") -> None:
    if not settings.langsmith_enabled:
        logger.debug("LangSmith disabilitato")
        return
    if not settings.langsmith_api_key:
        logger.warning("LangSmith abilitato ma LANGSMITH_API_KEY mancante — skip")
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    logger.info(
        "LangSmith tracing attivato",
        project=settings.langsmith_project,
        endpoint=settings.langsmith_endpoint,
    )

def setup_opentelemetry(settings: "AppSettings") -> None:
    if not settings.opentelemetry_enabled:
        logger.debug("OpenTelemetry disabilitato")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        resource = Resource.create({
            "service.name": settings.app_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.app_environment,
        })
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry configurato", service=settings.app_name)
    except ImportError:
        logger.warning("opentelemetry-sdk non installato — skip")

def _intercept_stdlib_logging() -> None:
    import logging
    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi",
                 "sqlalchemy.engine", "celery", "httpx"):
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False

