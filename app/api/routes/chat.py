from __future__ import annotations
import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import CurrentDB, CurrentRedis, CurrentTenant
from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/query", response_model=ChatResponse)
async def chat_query(
    request: ChatRequest,
    tenant: CurrentTenant,
    db: CurrentDB,
    redis: CurrentRedis,
) -> ChatResponse:
    service = ChatService(
        db=db,
        redis=redis,
        tenant_id=tenant.tenant_id,
        tenant_slug=tenant.tenant_slug,
        user_id=tenant.user_id,
    )
    result = await service.query(
        question=request.question,
        conversation_id=request.conversation_id,
        collection_id=request.collection_id,
    )
    return ChatResponse(**result)

@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    tenant: CurrentTenant,
    db: CurrentDB,
    redis: CurrentRedis,
) -> StreamingResponse:
    service = ChatService(
        db=db,
        redis=redis,
        tenant_id=tenant.tenant_id,
        tenant_slug=tenant.tenant_slug,
        user_id=tenant.user_id,
    )
    async def event_generator():
        try:
            meta: dict = {}
            async for token in service.stream_query(
                question=request.question,
                conversation_id=request.conversation_id,
                collection_id=request.collection_id,
            ):
                if token.startswith("\x1e"):

                    meta = json.loads(token[1:])
                else:
                    yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True, **meta})}\n\n"
        except Exception as e:
            logger.error(f"Errore streaming: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    tenant: CurrentTenant,
    db: CurrentDB,
) -> dict:
    from sqlalchemy import text
    await db.execute(
        text("""
            INSERT INTO message_feedback (message_id, user_id, rating, comment)
            VALUES (:msg_id, :user_id, :rating, :comment)
        """),
        {
            "msg_id": request.message_id,
            "user_id": tenant.user_id,
            "rating": request.rating,
            "comment": request.comment,
        }
    )
    return {"message": "Feedback salvato"}

