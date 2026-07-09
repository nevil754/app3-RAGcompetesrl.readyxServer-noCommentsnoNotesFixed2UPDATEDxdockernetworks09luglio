from __future__ import annotations
import time
from celery import shared_task
from loguru import logger
from sqlalchemy import text
from app.workers.celery_app import celery_app

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
    name="app.workers.ingestion_tasks.ingest_document",
)
def ingest_document(
    self,
    tenant_id: str,
    tenant_slug: str,
    document_id: str,
    file_path: str,
    collection_id: str | None = None,
) -> dict:
    from app.db.sqlserver import tenant_db
    from app.core.redis_client import TenantRedis
    from app.rag.ingestion.pipeline import run_ingestion_pipeline
    task_id = self.request.id
    log = logger.bind(
        task_id=task_id,
        tenant=tenant_slug,
        document_id=document_id,
    )
    log.info("Inizio ingestion documento")
    with tenant_db.get_session(tenant_slug) as session:
        session.execute(
            text("""
                UPDATE ingestion_jobs
                SET status = 'running',
                    started_at = SYSUTCDATETIME(),
                    celery_task_id = :task_id
                WHERE document_id = :doc_id
            """),
            {"task_id": task_id, "doc_id": document_id}
        )
        session.execute(
            text("UPDATE documents SET status = 'processing' WHERE id = :id"),
            {"id": document_id}
        )
    try:
        start = time.time()

        result = run_ingestion_pipeline(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            document_id=document_id,
            file_path=file_path,
            collection_id=collection_id,
        )
        elapsed_ms = round((time.time() - start) * 1000)
        log.info(
            "Pipeline completata",
            chunks=result["chunk_count"],
            elapsed_ms=elapsed_ms,
        )
        with tenant_db.get_session(tenant_slug) as session:
            session.execute(
                text("""
                    UPDATE ingestion_jobs
                    SET status = 'done',
                        finished_at = SYSUTCDATETIME(),
                        progress_pct = 100
                    WHERE document_id = :doc_id
                """),
                {"doc_id": document_id}
            )
            session.execute(
                text("""
                    UPDATE documents
                    SET status = 'ready',
                        chunk_count = :chunks,
                        page_count = :pages,
                        updated_at = SYSUTCDATETIME()
                    WHERE id = :id
                """),
                {
                    "chunks": result["chunk_count"],
                    "pages": result.get("page_count"),
                    "id": document_id,
                }
            )
        import asyncio
        redis = TenantRedis(tenant_id=tenant_id)
        loop = asyncio.new_event_loop()
        try:
            invalidated = loop.run_until_complete(redis.invalidate_query_cache())
        finally:
            loop.close()
        log.info(f"Cache invalidata: {invalidated} chiavi")
        return {
            "status": "done",
            "document_id": document_id,
            "chunk_count": result["chunk_count"],
            "elapsed_ms": elapsed_ms,
        }

    except Exception as exc:
        log.error(f"Ingestion fallita: {exc}")
        with tenant_db.get_session(tenant_slug) as session:
            retry_count = self.request.retries
            is_final = retry_count >= self.max_retries
            session.execute(
                text("""
                    UPDATE ingestion_jobs
                    SET status = :status,
                        error_msg = :err,
                        retry_count = :retries,
                        finished_at = CASE WHEN :is_final = 1 THEN GETUTCDATE() ELSE NULL END
                    WHERE document_id = :doc_id
                """),
                {
                    "status": "failed" if is_final else "queued",
                    "err": str(exc)[:2000],
                    "retries": retry_count + 1,
                    "is_final": 1 if is_final else 0,
                    "doc_id": document_id,
                }
            )
            if is_final:
                session.execute(
                    text("UPDATE documents SET status = 'error' WHERE id = :id"),
                    {"id": document_id}
                )
        if is_final:
            raise exc
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

@celery_app.task(
    bind=True,
    max_retries=2,
    acks_late=True,
    name="app.workers.ingestion_tasks.reprocess_document",
)
def reprocess_document(
    self,
    tenant_id: str,
    tenant_slug: str,
    document_id: str,
    file_path: str,
) -> dict:
    from app.core.vectorstore import get_qdrant_client, get_collection_name
    from qdrant_client.http import models as qmodels
    client = get_qdrant_client()
    collection = get_collection_name(tenant_slug)
    client.delete(
        collection_name=collection,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key="document_id",
                    match=qmodels.MatchValue(value=document_id)
                )]
            )
        )
    )
    logger.info(f"Vecchi vettori cancellati per documento {document_id}")
    task = ingest_document.apply_async(
        args=[tenant_id, tenant_slug, document_id, file_path],
        queue="low",
    )
    return {"status": "queued", "task_id": task.id, "document_id": document_id}

