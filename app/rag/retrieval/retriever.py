from __future__ import annotations
import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from loguru import logger
from app.core.settings import get_settings

settings = get_settings()

@dataclass
class RetrievedChunk:
    text: str
    score: float
    chunk_id: str
    document_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    doc_type: str
    metadata: dict[str, Any]

async def retrieve(
    query: str,
    tenant_slug: str,
    tenant_id: str,
    collection_id: str | None = None,
    top_k: int | None = None,
    filters: dict | None = None,
) -> list[RetrievedChunk]:
    k = top_k or settings.retriever_top_k
    logger.debug(f"Retrieval: query='{query[:50]}...', top_k={k}")
    from app.core.embeddings import aembed_query
    query_vector = await aembed_query(query)
    from app.core.vectorstore import get_async_qdrant_client, get_collection_name
    from qdrant_client.http import models as qmodels
    client = get_async_qdrant_client()
    collection_name = get_collection_name(tenant_slug)
    must_conditions = [
        qmodels.FieldCondition(
            key="tenant_id",
            match=qmodels.MatchValue(value=tenant_id)
        )
    ]
    if collection_id:
        must_conditions.append(
            qmodels.FieldCondition(
                key="collection_id",
                match=qmodels.MatchValue(value=collection_id)
            )
        )
    if filters:
        for key, value in filters.items():
            must_conditions.append(
                qmodels.FieldCondition(
                    key=key,
                    match=qmodels.MatchValue(value=value)
                )
            )
    qdrant_filter = qmodels.Filter(must=must_conditions)

    dense_results = await client.search(
        collection_name=collection_name,
        query_vector=qmodels.NamedVector(name="dense", vector=query_vector),
        query_filter=qdrant_filter,
        limit=k,
        with_payload=True,
        score_threshold=0.3,
    )

    sparse_results = []
    if settings.qdrant_use_sparse:
        try:
            sparse_vector = await _abuild_sparse_vector(query)
            sparse_results = await client.search(
                collection_name=collection_name,
                query_vector=qmodels.NamedSparseVector(name="sparse", vector=sparse_vector),
                query_filter=qdrant_filter,
                limit=k,
                with_payload=True,
            )
        except Exception as e:
            logger.warning(f"Sparse search fallita: {e}")

    fused = _rrf_fusion(dense_results, sparse_results, k=k)

    if settings.retriever_strategy == "mmr" and len(fused) > 1:
        fused = _mmr_rerank(query_vector, fused, lambda_param=settings.retriever_mmr_lambda)
    if settings.reranker_enabled and len(fused) > 1:
        fused = await _async_cross_encoder_rerank(query, fused, top_k=settings.reranker_top_k)

    chunks = []
    for item in fused:
        payload = item["payload"]
        chunks.append(RetrievedChunk(
            text=payload.get("text", ""),
            score=item["score"],
            chunk_id=item["id"],
            document_id=payload.get("document_id", ""),
            filename=payload.get("filename", ""),
            page_number=payload.get("page_number"),
            chunk_index=payload.get("chunk_index", 0),
            doc_type=payload.get("doc_type", "generic"),
            metadata=payload,
        ))
    logger.debug(f"Retrieval completato: {len(chunks)} chunk")
    return chunks

@lru_cache(maxsize=1)
def _get_splade_model() -> Any:
    from fastembed import SparseTextEmbedding
    logger.info("Caricamento modello SPLADE sparse", model="prithivida/Splade_PP_en_v1")
    return SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

def _build_sparse_vector(query: str) -> Any:
    model = _get_splade_model()
    vectors = list(model.embed([query]))
    v = vectors[0]
    return {"indices": v.indices.tolist(), "values": v.values.tolist()}

async def _abuild_sparse_vector(query: str) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _build_sparse_vector, query)

def _rrf_fusion(
    dense: list,
    sparse: list,
    k: int = 60,
) -> list[dict]:
    scores: dict[str, dict] = {}
    for rank, result in enumerate(dense):
        rid = str(result.id)
        if rid not in scores:
            scores[rid] = {
                "id": rid,
                "payload": result.payload,
                "score": 0.0
            }
        scores[rid]["score"] += 1.0 / (60 + rank + 1)
    for rank, result in enumerate(sparse):
        rid = str(result.id)
        if rid not in scores:
            scores[rid] = {
                "id": rid,
                "payload": result.payload,
                "score": 0.0
            }
        scores[rid]["score"] += 1.0 / (60 + rank + 1)
    return sorted( scores.values(), key=lambda x: x["score"], reverse=True )[:k]

def _mmr_rerank(
    query_vector: list[float],
    results: list[dict],
    lambda_param: float = 0.5,
    top_k: int | None = None,
) -> list[dict]:
    if not results:
        return results
    k = top_k or len(results)
    selected = []
    remaining = list( results )

    while len(selected) < k and remaining:
        if not selected:

            best = remaining[0]
        else:

            best_score = float("-inf")
            best = remaining[0]
            for candidate in remaining:
                relevance = candidate["score"]

                max_sim = max(
                    _score_similarity(candidate, sel) for sel in selected
                )
                mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
                if mmr_score > best_score:
                    best_score = mmr_score
                    best = candidate
        selected.append(best)
        remaining.remove(best)

    return selected

def _score_similarity(a: dict, b: dict) -> float:
    pa, pb = a["payload"], b["payload"]
    if pa.get("document_id") == pb.get("document_id"):
        diff = abs( pa.get("chunk_index", 0) - pb.get("chunk_index", 0) )

        return max(0, 1.0 - diff * 0.1)
    return 0.0

def _cross_encoder_rerank(
    query: str,
    results: list[dict],
    top_k: int,
) -> list[dict]:
    from app.core.embeddings import get_reranker_model
    reranker = get_reranker_model()
    if not reranker:
        return results[:top_k]
    pairs = [ (query, r["payload"].get("text", "")) for r in results ]
    scores = reranker.predict(pairs)
    for result, score in zip(results, scores):
        result["rerank_score"] = float(score)
    reranked = sorted(results, key=lambda x: x.get("rerank_score", 0), reverse=True)
    logger.debug(f"Reranking: {len(results)} → {top_k} chunk")
    return reranked[:top_k]

async def _async_cross_encoder_rerank(query: str, results: list[dict], top_k: int) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _cross_encoder_rerank, query, results, top_k)

