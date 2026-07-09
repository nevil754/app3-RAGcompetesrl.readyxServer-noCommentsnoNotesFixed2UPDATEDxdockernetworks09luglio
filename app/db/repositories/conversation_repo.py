from __future__ import annotations
import json
from app.db.repositories.base import BaseRepository

class ConversationRepository(BaseRepository):

    async def get_or_create(
        self,
        conversation_id: str,
        user_id: str,
        mode: str = "rag",
    ) -> dict:
        await self.execute(
            """
            IF NOT EXISTS (SELECT 1 FROM conversations WHERE id = :id)
                INSERT INTO conversations (id, user_id, mode)
                VALUES (:id, :user_id, :mode)
            """,
            {"id": conversation_id, "user_id": user_id, "mode": mode}
        )
        row = await self.fetchone(
            "SELECT * FROM conversations WHERE id = :id",
            {"id": conversation_id}
        )
        return dict(row._mapping) if row else {}

    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: list[dict] | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        hallucination_score: float | None = None,
    ) -> int:
        result = await self.execute(
            """
            INSERT INTO messages
                (conversation_id, role, content, sources, tokens_in, tokens_out, latency_ms, hallucination_score)
            OUTPUT INSERTED.id
            VALUES (:conv_id, :role, :content, :sources, :tokens_in, :tokens_out, :latency_ms, :hall_score)
            """,
            {
                "conv_id": conversation_id,
                "role": role,
                "content": content,
                "sources": json.dumps(sources or []),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "latency_ms": latency_ms,
                "hall_score": hallucination_score,
            }
        )
        row = result.fetchone()
        return row[0] if row else 0

    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> list[dict]:

        rows = await self.fetchall(
            """
            SELECT *
            FROM messages
            WHERE conversation_id = :conv_id
            ORDER BY created_at ASC
            OFFSET 0 ROWS FETCH NEXT :limit ROWS ONLY
            """,
            {"conv_id": conversation_id, "limit": limit}
        )
        return [ dict(r._mapping) for r in rows ]

    async def list_conversations(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        offset = (page-1) * page_size
        total = await self.scalar(
            "SELECT COUNT(*) FROM conversations WHERE user_id = :uid AND is_archived = 0",
            {"uid": user_id}
        )
        rows = await self.fetchall(
            """
            SELECT * FROM conversations
            WHERE user_id = :uid AND is_archived = 0
            ORDER BY updated_at DESC
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
            """,
            {"uid": user_id, "offset": offset, "limit": page_size}
        )
        return [dict(r._mapping) for r in rows], total or 0

    async def save_summary(
        self,
        conversation_id: str,
        user_id: str,
        summary_text: str,
        turn_count: int,
    ) -> None:
        await self.execute(
            """
            INSERT INTO conversation_summaries
                (conversation_id, user_id, summary_text, turn_count, from_turn, to_turn)
            VALUES (:conv_id, :user_id, :summary, :turns, 0, :turns)
            """,
            {
                "conv_id": conversation_id,
                "user_id": user_id,
                "summary": summary_text,
                "turns": turn_count,
            }
        )

    async def get_recent_summaries(self, user_id: str, limit: int = 3) -> list[str]:
        rows = await self.fetchall(
            """
            SELECT summary_text
            FROM conversation_summaries
            WHERE user_id = :uid
            ORDER BY created_at DESC
            OFFSET 0 ROWS FETCH NEXT :limit ROWS ONLY
            """,
            {"uid": user_id, "limit": limit}
        )
        return [ r.summary_text for r in rows ]

