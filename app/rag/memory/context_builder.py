from __future__ import annotations
from typing import Any
from loguru import logger
from app.rag.retrieval.retriever import RetrievedChunk

def build_rag_context(
    chunks: list[RetrievedChunk],
    session_messages: list[dict],
    user_facts: list[dict] | None = None,
    max_context_chars: int = 12000,
) -> dict[str, str]:
    context_parts = []
    total_chars = 0
    for i, chunk in enumerate(chunks, 1):
        source_label = f"[Fonte {i}: {chunk.filename}"
        if chunk.page_number:
            source_label += f", p.{chunk.page_number}"
        source_label += "]"
        chunk_text = f"{source_label}\n{chunk.text}"
        chunk_chars = len(chunk_text)
        if total_chars + chunk_chars > max_context_chars:
            logger.debug(f"Contesto troncato a {i-1} chunk per limite caratteri!")
            break
        context_parts.append(chunk_text)
        total_chars += chunk_chars
    context = "\n\n---\n\n".join(context_parts) if context_parts else ""
    history_parts = []
    for msg in session_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prefix = "Utente" if role == "user" else "Assistente"
        history_parts.append( f"{prefix}: {content}" )
    history = "\n".join(history_parts) if history_parts else "Nessuna conversazione precedente."
    facts_text = ""
    if user_facts:
        facts_parts = [ f"- { f['fact_key'] }: { f['fact_value'] }"  for f in user_facts ]
        facts_text = "\n".join( facts_parts )
    logger.debug(
        "Context assemblato",
        chunks=len(context_parts),
        history_turns=len(session_messages),
        context_chars=total_chars,
    )
    return {
        "context": context,
        "history": history,
        "facts": facts_text,
    }

def format_sources_for_response( chunks: list[RetrievedChunk] ) -> list[dict]:
    return [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "filename": chunk.filename,
            "page_number": chunk.page_number,
            "score": round(chunk.score, 4),
            "snippet": chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,
        }
        for chunk in chunks
    ]

