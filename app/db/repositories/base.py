from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

class BaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    async def execute(self, query: str, params: dict | None = None):
        return await self.db.execute(text(query), params or {})
    async def fetchone(self, query: str, params: dict | None = None):
        result = await self.execute(query, params)
        return result.fetchone()
    async def fetchall(self, query: str, params: dict | None = None):
        result = await self.execute(query, params)
        return result.fetchall()
    async def scalar(self, query: str, params: dict | None = None):
        result = await self.execute(query, params)
        return result.scalar()

