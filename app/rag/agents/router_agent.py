from __future__ import annotations
from typing import Literal
from langchain_core.messages import HumanMessage
from loguru import logger
from app.core.llm_factory import get_llm
from app.core.settings import get_settings

settings = get_settings()
QueryRoute = Literal["rag", "web", "sql", "general"]

async def route_query(question: str) -> QueryRoute:
    if not settings.web_search_enabled:
        return "rag"
    llm = get_llm()
    from app.rag.generation.prompts import _load_prompts
    prompts = _load_prompts()
    classify_prompt = prompts.get("router", {}).get("classify", _DEFAULT_CLASSIFY)
    try:
        response = await llm.ainvoke([
            HumanMessage( content=classify_prompt.format(question=question) )
        ])
        route = response.content.strip().lower()
        if route not in {"rag", "web", "sql", "general"}:
            logger.warning(f"Route non valida '{route}', default rag")
            route = "rag"
        logger.debug(f"Query routed to: {route}")
        return route
    except Exception as e:
        logger.warning(f"Router fallito: {e}, default rag")
        return "rag"

_DEFAULT_CLASSIFY = """Classifica la domanda in UNA di queste categorie:
    - rag: domanda su documenti caricati nel sistema
    - web: richiede informazioni aggiornate da internet
    - sql: domanda su dati strutturati o statistiche
    - general: domanda generica non legata a documenti
    Rispondi con SOLO la categoria, nessuna spiegazione.
    Domanda: {question}
Categoria:"""

