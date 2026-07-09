from __future__ import annotations
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from uuid import uuid4
from app.api.deps import AdminOnly, CurrentDB, CurrentTenant
from app.core.security import hash_password
from app.core.settings import get_settings

router = APIRouter(prefix="/users", tags=["users"])
settings = get_settings()

class UserCreate(BaseModel):
    email: EmailStr
    full_name: str | None = None
    password: str
    role: str = "user"

class UserSchema(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    class Config:
        from_attributes = True

@router.post("", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    tenant: AdminOnly,
    db: CurrentDB,
) -> UserSchema:
    if len(body.password) < settings.password_min_length:
        raise HTTPException(
            status_code=400,
            detail=f"Password troppo corta (min {settings.password_min_length} caratteri)"
        )
    user_id = str(uuid4())
    await db.execute(
        text("""
            INSERT INTO users (id, email, full_name, role, password_hash)
            VALUES (:id, :email, :name, :role, :pwd_hash)
        """),
        {
            "id": user_id,
            "email": body.email,
            "name": body.full_name,
            "role": body.role,
            "pwd_hash": hash_password( body.password ),
        }
    )
    row = await db.execute(
        text("SELECT id, email, full_name, role, is_active FROM users WHERE id = :id"),
        {"id": user_id}
    )
    return UserSchema.model_validate( dict( row.fetchone()._mapping ) )

@router.get("", response_model=list[UserSchema])
async def list_users( tenant: AdminOnly, db: CurrentDB ) -> list[UserSchema]:
    rows = await db.execute(
        text( "SELECT id, email, full_name, role, is_active FROM users ORDER BY created_at DESC" )
    )
    return [ UserSchema.model_validate(dict(r._mapping)) for r in rows ]

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(user_id: str, tenant: AdminOnly, db: CurrentDB) -> None:
    await db.execute(
        text("UPDATE users SET is_active = 0 WHERE id = :id"),
        {"id": user_id}
    )

