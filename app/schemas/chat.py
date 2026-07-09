from __future__ import annotations
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str | None = None
    collection_id: str | None = None

class SourceSchema(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int | None = None
    score: float
    snippet: str

class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    message_id: int
    sources: list[SourceSchema] = []
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None

class FeedbackRequest(BaseModel):
    message_id: int
    rating: int = Field(..., ge=-1, le=1)
    comment: str | None = None

