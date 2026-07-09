from __future__ import annotations
from celery import Celery
from kombu import Queue
from app.core.settings import get_settings

settings = get_settings()

def create_celery_app() -> Celery:
    app = Celery(
        "rag_worker",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )

    app.conf.update(

        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],

        result_expires=86400,
        task_track_started=True,

        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,

        task_queues=[
            Queue("high",           routing_key="high"),
            Queue("default",        routing_key="default"),
            Queue("low",            routing_key="low"),
            Queue("shared_cleanup", routing_key="shared_cleanup"),
        ],
        task_default_queue="default",
        task_routes={
            "app.workers.ingestion_tasks.ingest_document":   {"queue": "default"},
            "app.workers.ingestion_tasks.reprocess_document":{"queue": "low"},
            "app.workers.cleanup_tasks.purge_tenant":        {"queue": "shared_cleanup"},
            "app.workers.cleanup_tasks.expire_sessions":     {"queue": "shared_cleanup"},
            "app.workers.scheduled_tasks.rollup_usage":      {"queue": "shared_cleanup"},
        },
        task_max_retries=3,
        task_default_retry_delay=60,
        timezone="UTC",
        enable_utc=True,

        beat_scheduler="redbeat.RedBeatScheduler",
        redbeat_redis_url=settings.redis_url,
        redbeat_key_prefix="redbeat:",
    )
    return app

celery_app = create_celery_app()

