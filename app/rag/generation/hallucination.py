from __future__ import annotations
from loguru import logger
from app.rag.retrieval.retriever import RetrievedChunk

async def check_faithfulness(
    question: str,
    answer: str,
    chunks: list[RetrievedChunk],
) -> float:
    if not chunks or not answer:
        return 1.0
    context = "\n\n".join(c.text for c in chunks[:5])
    try:
        from app.core.llm_factory import get_llm
        from langchain_core.messages import HumanMessage

        llm = get_llm()
        response = await llm.ainvoke([
            HumanMessage(content=f"""Valuta se la RISPOSTA è completamente supportata dal CONTESTO.
                Rispondi SOLO con un numero tra 0.0 e 1.0.
                1.0 = completamente supportata, 0.0 = per niente supportata.
                CONTESTO:
                {context}
                RISPOSTA:
                {answer}
                SCORE (solo il numero):""")
        ])
        score_text = response.content.strip()
        score = float(score_text)
        score = max(0.0, min(1.0, score))
        logger.debug(f"Hallucination score: {score:.2f}")
        return score
    except Exception as e:
        logger.warning(f"Hallucination check fallito: {e}")
        return 1.0

def is_hallucination(score: float, threshold: float = 0.5) -> bool:
    return score < threshold

