from __future__ import annotations
import json
from dataclasses import dataclass
from loguru import logger
from app.core.redis_client import TenantRedis
from app.core.settings import get_settings

settings = get_settings()

@dataclass
class ChatMessage:
    role: str
    content: str

class ShortTermMemory:
    def __init__(self, redis: TenantRedis, conversation_id: str):
        self.redis = redis
        self.conversation_id = conversation_id
        self.max_turns = settings.memory_short_term_turns

    async def add(self, role: str, content: str) -> None:
        await self.redis.append_message(
            session_id=self.conversation_id,
            message={"role": role, "content": content},
            max_turns=self.max_turns,
        )

    async def get_all(self) -> list[ChatMessage]:
        raw = await self.redis.get_session(self.conversation_id)
        return [ ChatMessage(role=m["role"], content=m["content"]) for m in raw ]

    async def get_formatted(self) -> str:
        messages = await self.get_all()
        if not messages:
            return "Nessuna conversazione precedente."
        lines = []
        for msg in messages:
            prefix = "Utente" if msg.role == "user" else "Assistente"
            lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)

    async def clear(self) -> None:
        await self.redis.clear_session(self.conversation_id)

    async def count(self) -> int:
        messages = await self.get_all()
        return len(messages)

