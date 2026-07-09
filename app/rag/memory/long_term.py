from __future__ import annotations
import json
from typing import Any
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.settings import get_settings

settings = get_settings()

class LongTermMemory:
    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        tenant_slug: str,
        user_id: str,
    ):
        self.db = db
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.user_id = user_id

    async def summarize_conversation(
        self,
        conversation_id: str,
        messages: list[dict],
    ) -> str:
        if not settings.memory_long_term_enabled:
            return ""
        from app.core.llm_factory import get_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        history = "\n".join(
            f" {'Utente' if m['role'] == 'user' else 'Assistente'}: {m['content']} "
            for m in messages
        )
        llm = get_llm()
        response = await llm.ainvoke([
            SystemMessage(content="Sei un assistente che riassume conversazioni legali in modo conciso e strutturato."),
            HumanMessage(content=f"""Riassumi questa conversazione legale in 3-5 frasi.
                Mantieni: decisioni prese, documenti citati, questioni aperte.

                CONVERSAZIONE:
                {history}

                RIASSUNTO:""")
        ])
        summary = response.content
        await self.db.execute(
            text("""
                INSERT INTO conversation_summaries
                    (conversation_id, user_id, summary_text, turn_count, from_turn, to_turn)
                VALUES (:conv_id, :user_id, :summary, :turns, 0, :turns)
            """),
            {
                "conv_id": conversation_id,
                "user_id": self.user_id,
                "summary": summary,
                "turns": len(messages),
            }
        )
        logger.info(
            "Summary conversazione salvato",
            conversation_id=conversation_id,
            turns=len(messages),
        )
        return summary

    async def extract_facts(
        self,
        conversation_id: str,
        messages: list[dict],
    ) -> list[dict]:
        if not settings.memory_long_term_enabled:
            return []
        from app.core.llm_factory import get_llm
        from langchain_core.messages import HumanMessage

        history = "\n".join(
            f"{m['role']}: {m['content']}" for m in messages[-20:]
        )
        llm = get_llm()
        response = await llm.ainvoke([
            HumanMessage(content=f"""Analizza questa conversazione ed estrai fatti permanenti sull'utente.
                Rispondi SOLO con un JSON array. Nessun testo aggiuntivo.
                Tipi di fatti:
                - preference: preferenze esplicite o implicite
                - expertise: aree di competenza dimostrate
                - context: ruolo/contesto lavorativo
                - entity: clienti, aziende, persone menzionate frequentemente
                - instruction: istruzioni su come l'assistente deve comportarsi
                CONVERSAZIONE:
                {history}

                JSON:
                [{{"type": "...", "key": "...", "value": "...", "confidence": 0.0}}]""")
        ])
        try:
            raw = response.content.strip()
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            facts = json.loads(raw)
        except Exception as e:
            logger.warning(f"Parsing fatti fallito: {e}")
            return []

        for fact in facts:
            await self._upsert_fact(conversation_id, fact)
        logger.info(f"Estratti {len(facts)} fatti per utente {self.user_id}")
        return facts

    async def _upsert_fact(self, source_conv_id: str, fact: dict) -> None:
        await self.db.execute(
            text("""
                MERGE user_facts AS target
                USING (VALUES (:user_id, :fact_type, :fact_key, :fact_value,
                               :confidence, :conv_id))
                AS source (user_id, fact_type, fact_key, fact_value,
                           confidence, source_conv_id)
                ON target.user_id = source.user_id
                   AND target.fact_key = source.fact_key
                   AND target.is_active = 1
                WHEN MATCHED THEN UPDATE SET
                    fact_value = source.fact_value,
                    confidence = source.confidence,
                    updated_at = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT
                    (user_id, fact_type, fact_key, fact_value, confidence, source_conv_id)
                VALUES (source.user_id, source.fact_type, source.fact_key,
                        source.fact_value, source.confidence, source.source_conv_id);
            """),

            {
                "user_id": self.user_id,
                "fact_type": fact.get("type", "generic"),
                "fact_key": fact.get("key", ""),
                "fact_value": fact.get("value", ""),
                "confidence": fact.get("confidence", 1.0),
                "conv_id": source_conv_id,
            }
        )

    async def get_user_facts(self, limit: int = 20) -> list[dict]:
        if not settings.memory_long_term_enabled:
            return []
        rows = await self.db.execute(
            text("""
                SELECT fact_type, fact_key, fact_value, confidence
                FROM user_facts
                WHERE user_id = :user_id AND is_active = 1
                ORDER BY confidence DESC, updated_at DESC
                OFFSET 0 ROWS FETCH NEXT :limit ROWS ONLY
            """),
            {"user_id": self.user_id, "limit": limit}
        )
        return [ dict(r._mapping) for r in rows ]

    async def get_recent_summaries(self, limit: int = 3) -> str:
        if not settings.memory_long_term_enabled:
            return ""
        rows = await self.db.execute(
            text("""
                SELECT summary_text, created_at
                FROM conversation_summaries
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                OFFSET 0 ROWS FETCH NEXT :limit ROWS ONLY
            """),
            {"user_id": self.user_id, "limit": limit}
        )
        summaries = [ r.summary_text for r in rows ]
        if not summaries:
            return ""
        return "CONVERSAZIONI PRECEDENTI:\n" + "\n---\n".join(summaries)

