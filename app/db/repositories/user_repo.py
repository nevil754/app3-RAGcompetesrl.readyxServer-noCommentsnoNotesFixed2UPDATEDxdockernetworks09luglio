from __future__ import annotations
from app.core.security import hash_password
from app.db.repositories.base import BaseRepository

class UserRepository(BaseRepository):
    async def get_by_email(self, email: str) -> dict | None:
        row = await self.fetchone(
            "SELECT * FROM users WHERE email = :email",
            {"email": email}
        )
        return dict(row._mapping) if row else None

    async def get_by_id(self, user_id: str) -> dict | None:
        row = await self.fetchone(
            "SELECT * FROM users WHERE id = :id",
            {"id": user_id}
        )
        return dict(row._mapping) if row else None

    async def create(
        self,
        user_id: str,
        email: str,
        password: str,
        role: str = "user",
        full_name: str | None = None,
    ) -> dict:
        await self.execute(
            """
            INSERT INTO users (id, email, full_name, role, password_hash)
            VALUES (:id, :email, :name, :role, :pwd)
            """,
            {
                "id": user_id,
                "email": email,
                "name": full_name,
                "role": role,
                "pwd": hash_password(password),
            }
        )
        return await self.get_by_id(user_id) or {}

    async def update_last_login(self, user_id: str) -> None:
        await self.execute(
            "UPDATE users SET last_login = SYSUTCDATETIME() WHERE id = :id",
            {"id": user_id}
        )

    async def deactivate(self, user_id: str) -> None:
        await self.execute(
            "UPDATE users SET is_active = 0 WHERE id = :id",
            {"id": user_id}
        )

    async def list_all(self) -> list[dict]:
        rows = await self.fetchall(
            """
            SELECT id, email, full_name, role, is_active, created_at
            FROM users ORDER BY created_at DESC
            """
        )
        return [ dict(r._mapping) for r in rows ]

