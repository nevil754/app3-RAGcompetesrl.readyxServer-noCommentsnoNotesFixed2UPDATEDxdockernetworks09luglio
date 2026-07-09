from __future__ import annotations
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.api.deps import CurrentDB, CurrentTenant
from app.schemas.common import PaginatedResponse
from app.schemas.document import IngestionJobSchema

router = APIRouter(prefix="/jobs", tags=["jobs"])

@router.get("", response_model=PaginatedResponse[IngestionJobSchema])
async def list_jobs(
    tenant: CurrentTenant,
    db: CurrentDB,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> PaginatedResponse[IngestionJobSchema]:
    offset = (page-1)*page_size
    where = "WHERE 1=1"
    params: dict = {"limit": page_size, "offset": offset}
    if status:
        where += " AND status = :status"
        params["status"] = status
    total_row = await db.execute( text(f"SELECT COUNT(*) FROM ingestion_jobs {where}"), params )
    total = total_row.scalar() or 0
    rows = await db.execute(
        text(f"""
            SELECT id, document_id, celery_task_id, status, progress_pct,
                   error_msg, retry_count, started_at, finished_at, created_at
            FROM ingestion_jobs {where}
            ORDER BY created_at DESC
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """),
        params
    )
    items = [IngestionJobSchema.model_validate(dict(r._mapping)) for r in rows]
    return PaginatedResponse.build(items=items, total=total, page=page, page_size=page_size)

@router.get("/{job_id}", response_model=IngestionJobSchema)
async def get_job(
    job_id: str,
    tenant: CurrentTenant,
    db: CurrentDB,
) -> IngestionJobSchema:
    row = await db.execute(
        text("""
            SELECT id, document_id, celery_task_id, status, progress_pct,
                   error_msg, retry_count, started_at, finished_at, created_at
            FROM ingestion_jobs WHERE id = :id
        """),
        {"id": job_id}
    )
    job = row.fetchone()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return IngestionJobSchema.model_validate(dict(job._mapping))

@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    tenant: CurrentTenant,
    db: CurrentDB,
) -> dict:
    row = await db.execute(
        text("SELECT status FROM ingestion_jobs WHERE id = :id"),
        {"id": job_id}
    )
    job = row.fetchone()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=400, detail=f"Job non annullabile in stato: {job.status}")
    from app.workers.celery_app import celery_app
    task_row = await db.execute(
        text("SELECT celery_task_id FROM ingestion_jobs WHERE id = :id"),
        {"id": job_id}
    )
    task_row_data = task_row.fetchone()
    if task_row_data and task_row_data.celery_task_id:
        celery_app.control.revoke(task_row_data.celery_task_id, terminate=True)
    await db.execute(
        text("UPDATE ingestion_jobs SET status = 'cancelled' WHERE id = :id"),
        {"id": job_id}
    )
    return {"message": "Job cancellato", "job_id": job_id}

