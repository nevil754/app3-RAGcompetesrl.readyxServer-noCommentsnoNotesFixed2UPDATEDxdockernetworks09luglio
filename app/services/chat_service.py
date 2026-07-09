from __future__ import annotations
import hashlib
import json
import time
from typing import AsyncGenerator, Any
from uuid import uuid4
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.redis_client import TenantRedis
from app.core.settings import get_settings
from app.rag.retrieval.retriever import retrieve
from app.rag.generation.chain import arun_rag_chain, astream_rag_chain
from app.rag.generation.answer_validator import validate_answer
from app.rag.generation.hallucination import check_faithfulness, is_hallucination
from app.rag.memory.context_builder import format_sources_for_response

settings = get_settings()

class ChatService:

    def __init__(
        self,
        db: AsyncSession,
        redis: TenantRedis,
        tenant_id: str,
        tenant_slug: str,
        user_id: str,
    ):
        self.db = db
        self.redis = redis
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.user_id = user_id

    async def query(
        self,
        question: str,
        conversation_id: str | None = None,
        collection_id: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        conv_id = conversation_id or str(uuid4())
        query_hash = _hash_query( question, conv_id )
        cached = await self.redis.get_query_cache(query_hash)
        if cached:
            logger.debug("Cache hit per query RAG")
            return json.loads(cached)
        session_messages = await self.redis.get_session(conv_id)
        chunks = await retrieve(
            query=question,
            tenant_slug=self.tenant_slug,
            tenant_id=self.tenant_id,
            collection_id=collection_id,
        )
        result = await arun_rag_chain(
            question=question,
            chunks=chunks,
            session_messages=session_messages,
        )

        validation = validate_answer(result["answer"], question)
        if validation.was_modified:
            result["answer"] = validation.answer
            logger.debug("Risposta corretta dal validator", issues=validation.issues)

        hall_score = await check_faithfulness(question, result["answer"], chunks)
        if is_hallucination(hall_score):
            logger.warning(
                "Potenziale allucinazione rilevata",
                score=hall_score,
                question=question[:80],
            )
        message_id = await self._save_messages(
            conv_id=conv_id,
            question=question,
            answer=result["answer"],
            sources=result["sources"],
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            latency_ms=result.get("latency_ms", 0),
            hallucination_score=hall_score,
        )
        await self.redis.append_message( conv_id, {
            "role": "user", "content": question
        }, settings.memory_short_term_turns)

        await self.redis.append_message(conv_id, {
            "role": "assistant", "content": result["answer"]
        }, settings.memory_short_term_turns)

        response = {
            "answer": result["answer"],
            "conversation_id": conv_id,
            "message_id": message_id,
            "sources": result["sources"],
            "tokens_in": result.get("tokens_in"),
            "tokens_out": result.get("tokens_out"),
            "latency_ms": result.get("latency_ms"),
        }
        await self.redis.set_query_cache( query_hash, json.dumps(response) )
        await self._increment_usage_stats(
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
        )
        return response

    async def stream_query(
        self,
        question: str,
        conversation_id: str | None = None,
        collection_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        conv_id = conversation_id or str(uuid4())
        query_hash = _hash_query(question, conv_id)
        cached = await self.redis.get_query_cache(query_hash)
        if cached:
            logger.debug("Cache hit per query RAG (streaming)")
            cached_data = json.loads(cached)
            yield cached_data.get("answer", "")

            yield "\x1e" + json.dumps({
                "sources": cached_data.get("sources", []),
                "conversation_id": conv_id,
                "latency_ms": cached_data.get("latency_ms"),
            })
            return
        session_messages = await self.redis.get_session(conv_id)
        chunks = await retrieve(
            query=question,
            tenant_slug=self.tenant_slug,
            tenant_id=self.tenant_id,
            collection_id=collection_id,
        )
        start = time.time()
        full_answer = ""
        async for token in astream_rag_chain(
            question=question,
            chunks=chunks,
            session_messages=session_messages,
        ):
            full_answer += token
            yield token
        latency_ms = round((time.time() - start) * 1000)

        validation = validate_answer(full_answer, question)
        if validation.was_modified:
            full_answer = validation.answer
            logger.debug("Risposta streaming corretta dal validator", issues=validation.issues)

        hall_score = await check_faithfulness(question, full_answer, chunks)
        if is_hallucination(hall_score):
            logger.warning(
                "Potenziale allucinazione rilevata (streaming)",
                score=hall_score,
                question=question[:80],
            )
        await self._save_messages(
            conv_id=conv_id,
            question=question,
            answer=full_answer,
            sources=format_sources_for_response(chunks),
            latency_ms=latency_ms,
            hallucination_score=hall_score,
        )
        await self.redis.append_message(conv_id, {"role": "user", "content": question}, settings.memory_short_term_turns)
        await self.redis.append_message(conv_id, {"role": "assistant", "content": full_answer}, settings.memory_short_term_turns)
        sources = format_sources_for_response(chunks)
        response_to_cache = {
            "answer": full_answer,
            "conversation_id": conv_id,
            "sources": sources,
            "latency_ms": latency_ms,
        }
        await self.redis.set_query_cache(query_hash, json.dumps(response_to_cache))
        yield "\x1e" + json.dumps({
            "sources": sources,
            "conversation_id": conv_id,
            "latency_ms": latency_ms,
            "hallucination_score": round(hall_score, 3),
        })

    async def _save_messages(
        self,
        conv_id: str,
        question: str,
        answer: str,
        sources: list[dict],
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        hallucination_score: float | None = None,
    ) -> int:
        from app.core.settings import get_settings
        settings = get_settings()
        await self.db.execute(
            text("""
                IF NOT EXISTS (SELECT 1 FROM conversations WHERE id = :id)
                INSERT INTO conversations (id, user_id, mode)
                VALUES (:id, :user_id, 'rag')
            """),
            {"id": conv_id, "user_id": self.user_id}
        )

        await self.db.execute(
            text("""
                INSERT INTO messages (conversation_id, role, content)
                VALUES (:conv_id, 'user', :content)
            """),
            {"conv_id": conv_id, "content": question}
        )

        result = await self.db.execute(
            text("""
                INSERT INTO messages
                    (conversation_id, role, content, sources, tokens_in, tokens_out, latency_ms, hallucination_score)
                OUTPUT INSERTED.id
                VALUES (:conv_id, 'assistant', :content, :sources, :tokens_in, :tokens_out, :latency_ms, :hall_score)
            """),
            {
                "conv_id": conv_id,
                "content": answer,
                "sources": json.dumps(sources),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "latency_ms": latency_ms,
                "hall_score": hallucination_score,
            }
        )
        row = result.fetchone()
        return row[0] if row else 0

    async def _increment_usage_stats( self, tokens_in: int, tokens_out: int ) -> None:
        from datetime import date
        today = date.today().isoformat()
        base = f"tenant:{self.tenant_id}:stats:{today}"
        pipe = self.redis._redis.pipeline()

        pipe.incrby(f"{base}:tokens_in", tokens_in)
        pipe.incrby(f"{base}:tokens_out", tokens_out)
        pipe.incr(f"{base}:queries")

        pipe.expire(f"{base}:tokens_in", 172800)
        pipe.expire(f"{base}:tokens_out", 172800)
        pipe.expire(f"{base}:queries", 172800)
        await pipe.execute()

def _hash_query(question: str, conv_id: str) -> str:
    normalized = question.strip().lower()
    return hashlib.md5(f"{conv_id}:{normalized}".encode()).hexdigest()

