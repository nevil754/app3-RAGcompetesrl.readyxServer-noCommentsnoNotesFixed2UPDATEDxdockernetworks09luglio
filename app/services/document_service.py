from __future__ import annotations
import hashlib
import os
import shutil
from pathlib import Path
from uuid import uuid4
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.settings import get_settings

settings = get_settings()

UPLOAD_DIR = Path("/app/uploads")

class DocumentService:

    def __init__(self, db: AsyncSession, tenant_id: str, tenant_slug: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.user_id = user_id

    async def upload_and_queue(
        self,
        file_bytes: bytes,
        original_filename: str,
        collection_id: str | None = None,
    ) -> dict:

        max_bytes = settings.ingestion_max_file_mb * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise ValueError(
                f"File troppo grande: { len(file_bytes) // 1024 // 1024 }MB "
                f"(max {settings.ingestion_max_file_mb}MB)"
            )
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        existing = await self.db.execute(
            text("SELECT id FROM documents WHERE file_hash = :hash"),
            {"hash": file_hash}
        )
        if existing.fetchone():
            raise ValueError(f"Documento già caricato: {original_filename}")

        document_id = str(uuid4())
        suffix = Path(original_filename).suffix
        saved_filename = f"{document_id}{suffix}"
        file_path = UPLOAD_DIR / self.tenant_slug / saved_filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        import mimetypes
        mime_type = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"

        await self.db.execute(
            text("""
                INSERT INTO documents
                    (id, collection_id, filename, original_name, file_hash,
                     file_size, mime_type, storage_path, status, uploaded_by)
                VALUES
                    (:id, :coll_id, :filename, :orig_name, :hash,
                     :size, :mime, :path, 'pending', :user_id)
            """),
            {
                "id": document_id,
                "coll_id": collection_id,
                "filename": saved_filename,
                "orig_name": original_filename,
                "hash": file_hash,
                "size": len(file_bytes),
                "mime": mime_type,
                "path": str(file_path),
                "user_id": self.user_id,
            }
        )
        job_id = str(uuid4())
        await self.db.execute(
            text("""
                INSERT INTO ingestion_jobs (id, document_id, status)
                VALUES (:id, :doc_id, 'queued')
            """),
            {"id": job_id, "doc_id": document_id}
        )
        from app.workers.ingestion_tasks import ingest_document
        task = ingest_document.apply_async(
            args=[
                self.tenant_id,
                self.tenant_slug,
                document_id,
                str(file_path),
                collection_id,
            ],
            queue="default",
            countdown=3,
            headers={"tenant_id": self.tenant_id},
        )
        logger.info(
            "Documento in coda",
            document_id=document_id,
            filename=original_filename,
            task_id=task.id,
        )
        return {
            "document_id": document_id,
            "job_id": job_id,
            "task_id": task.id,
            "status": "queued",
        }

