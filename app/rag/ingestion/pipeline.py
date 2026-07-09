from __future__ import annotations
import hashlib
import uuid
from pathlib import Path
from typing import Any
from loguru import logger
from app.rag.ingestion.parser import parse_document
from app.rag.ingestion.cleaner import clean_text
from app.rag.ingestion.chunker import chunk_document
from app.rag.ingestion.metadata import build_chunk_metadata
from app.core.embeddings import embed_texts
from app.core.vectorstore import get_qdrant_client, get_collection_name, ensure_collection
from app.core.settings import get_settings

settings = get_settings()

def run_ingestion_pipeline(
    tenant_id: str,
    tenant_slug: str,
    document_id: str,
    file_path: str,
    collection_id: str | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    filename = path.name
    file_type = path.suffix
    logger.info(
        "Pipeline ingestion avviata",
        file=filename,
        tenant=tenant_slug,
        document_id=document_id,
    )
    parsed = parse_document(file_path)
    logger.debug( f"Parsing: {parsed.page_count} pagine, {len(parsed.text)} chars" )
    clean = clean_text(parsed.text)
    logger.debug( f"Pulizia: { len(parsed.text) } → { len(clean) } chars" )
    base_metadata = {
        "tenant_id": tenant_id,
        "document_id": document_id,
        "filename": filename,
    }
    chunks = chunk_document( clean, pages=parsed.pages, base_metadata=base_metadata )
    logger.debug( f"Chunking: {len(chunks)} chunk" )
    if not chunks:
        raise ValueError(f"Nessun chunk estratto dal documento {filename}")
    texts = [ c.text for c in chunks ]
    vectors = embed_texts(texts)
    logger.debug( f"Embedding: {len(vectors)} vettori generati" )
    if settings.qdrant_use_sparse:
        from app.core.embeddings import embed_sparse_texts
        sparse_vectors: list[dict | None] = embed_sparse_texts(texts)
        logger.debug( f"Sparse embedding: {len(sparse_vectors)} vettori generati" )
    else:
        sparse_vectors = [None] * len(vectors)
    collection_name = ensure_collection( tenant_slug, settings.qdrant_force_recreate )
    client = get_qdrant_client()
    from qdrant_client.http import models as qmodels
    points = []
    for chunk, vector, sparse_vec in zip( chunks, vectors, sparse_vectors ):
        payload = build_chunk_metadata(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            filename=filename,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
            file_type=file_type,
            document_text_sample=clean[:500],
        )
        payload["text"] = chunk.text
        vector_dict: dict = {"dense": vector}
        if sparse_vec is not None:
            vector_dict["sparse"] = qmodels.SparseVector(
                indices=sparse_vec["indices"],
                values=sparse_vec["values"],
            )
        points.append( qmodels.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector_dict,
            payload=payload,
        ) )

    batch_size = 100
    for i in range( 0, len(points), batch_size ):
        batch = points[i:i + batch_size]
        client.upsert(collection_name=collection_name, points=batch)
        logger.debug(f"Upserted batch {i // batch_size + 1}: { len(batch) } punti")
    logger.info(
        "Pipeline ingestion completata",
        file=filename,
        chunks=len(chunks),
        collection=collection_name,
    )
    return {
        "chunk_count": len(chunks),
        "page_count": parsed.page_count,
        "collection_name": collection_name,
    }

