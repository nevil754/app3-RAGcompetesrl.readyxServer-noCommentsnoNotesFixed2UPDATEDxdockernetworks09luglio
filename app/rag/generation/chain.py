from __future__ import annotations
import time
from typing import AsyncGenerator, Any
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from app.core.llm_factory import get_llm
from app.rag.generation.prompts import (
    get_rag_system_prompt,
    get_rag_user_prompt,
    get_no_context_message,
)
from app.rag.retrieval.retriever import RetrievedChunk
from app.rag.memory.context_builder import build_rag_context, format_sources_for_response

async def arun_rag_chain(
    question: str,
    chunks: list[RetrievedChunk],
    session_messages: list[dict],
    tenant_name: str = "Compet-e Compliance AI",
) -> dict[str, Any]:
    start = time.perf_counter()
    if not chunks:
        return {
            "answer": get_no_context_message(),
            "sources": [],
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": 0,
        }
    ctx = build_rag_context(chunks, session_messages)

    system_msg = SystemMessage( content= get_rag_system_prompt(tenant_name) )
    user_msg = HumanMessage( content=get_rag_user_prompt(
        context=ctx["context"],
        history=ctx["history"],
        question=question,
    ))
    llm = get_llm()
    response = await llm.ainvoke([system_msg, user_msg])
    answer = response.content
    usage = getattr( response, "usage_metadata", None ) or {}
    tokens_in = usage.get("input_tokens", 0)
    tokens_out = usage.get("output_tokens", 0)
    latency_ms = round((time.perf_counter() - start) * 1000)
    logger.debug(
        "RAG chain completata",
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        sources=len(chunks),
    )
    return {
        "answer": answer,
        "sources": format_sources_for_response(chunks),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
    }

async def astream_rag_chain(
    question: str,
    chunks: list[RetrievedChunk],
    session_messages: list[dict],
    tenant_name: str = "Compet-e Compliance AI",
) -> AsyncGenerator[str, None]:
    if not chunks:
        yield get_no_context_message()
        return
    ctx = build_rag_context(chunks, session_messages)
    system_msg = SystemMessage( content=get_rag_system_prompt(tenant_name) )
    user_msg = HumanMessage( content=get_rag_user_prompt(
        context=ctx["context"],
        history=ctx["history"],
        question=question,
    ))
    llm = get_llm()
    async for chunk in llm.astream([system_msg, user_msg]):
        token = chunk.content
        if token:
            yield token

