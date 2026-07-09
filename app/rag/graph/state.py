from __future__ import annotations
from typing import Any, TypedDict
from app.rag.retrieval.retriever import RetrievedChunk

class RAGState(TypedDict):

    question: str
    conversation_id: str
    tenant_id: str
    tenant_slug: str
    user_id: str
    collection_id: str | None
    mode: str

    route: str | None
    retrieved_chunks: list[RetrievedChunk]
    session_messages: list[dict]
    web_results: dict | None

    answer: str
    sources: list[dict]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    hallucination_score: float | None
    error: str | None

