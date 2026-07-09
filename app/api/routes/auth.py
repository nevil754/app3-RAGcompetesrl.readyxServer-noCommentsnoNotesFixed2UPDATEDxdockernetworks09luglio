from __future__ import annotations
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from pydantic import BaseModel, EmailStr
from sqlalchemy import text

from app.api.deps import CurrentTenant, get_current_tenant
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.core.settings import get_settings
from app.db.sqlserver import tenant_db

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    user_role: str
    tenant_slug: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str

class UserProfile(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str
    tenant_id: str
    tenant_slug: str

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest) -> TokenResponse:

    async with tenant_db._async_factory() as session:
        tenant_row = await session.execute(
            text("""
                SELECT id, slug, is_active
                FROM shared.tenants
                WHERE slug = :slug
            """),
            {"slug": request.tenant_slug}
        )
        tenant = tenant_row.fetchone()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
        )
    if not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account tenant disabilitato",
        )

    async with tenant_db.aget_session(request.tenant_slug) as session:
        user_row = await session.execute(
            text("""
                SELECT id, email, full_name, password_hash, role, is_active
                FROM users
                WHERE email = :email
            """),
            {"email": request.email}
        )
        user = user_row.fetchone()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account utente disabilitato",
        )

    if not verify_password(request.password, user.password_hash):
        logger.warning(
            "Tentativo login fallito",
            email=request.email,
            tenant=request.tenant_slug,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
        )

    async with tenant_db.aget_session(request.tenant_slug) as session:
        await session.execute(
            text("UPDATE users SET last_login = SYSUTCDATETIME() WHERE id = :id"),
            {"id": user.id}
        )

    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "tenant_id": str(tenant.id),
        "tenant_slug": tenant.slug,
    })
    logger.info("Login effettuato", user_id=str(user.id), tenant=request.tenant_slug)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        user_id=str(user.id),
        user_role=user.role,
        tenant_slug=tenant.slug,
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(tenant: CurrentTenant) -> TokenResponse:
    new_token = create_access_token(data={
        "sub": tenant.user_id,
        "email": tenant.user_email,
        "role": tenant.user_role,
        "tenant_id": tenant.tenant_id,
        "tenant_slug": tenant.tenant_slug,
    })
    return TokenResponse(
        access_token=new_token,
        expires_in=settings.jwt_expire_minutes * 60,
        user_id=tenant.user_id,
        user_role=tenant.user_role,
        tenant_slug=tenant.tenant_slug,
    )

@router.get("/me", response_model=UserProfile)
async def get_profile(tenant: CurrentTenant) -> UserProfile:
    async with tenant_db.aget_session(tenant.tenant_slug) as session:
        row = await session.execute(
            text("SELECT id, email, full_name, role FROM users WHERE id = :id"),
            {"id": tenant.user_id}
        )
        user = row.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return UserProfile(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        tenant_id=tenant.tenant_id,
        tenant_slug=tenant.tenant_slug,
    )

@router.post("/logout")
async def logout(tenant: CurrentTenant) -> dict:
    from app.core.redis_client import TenantRedis
    redis = TenantRedis(tenant_id=tenant.tenant_id)
    async with tenant_db.aget_session(tenant.tenant_slug) as session:
        rows = await session.execute(
            text("SELECT id FROM conversations WHERE user_id = :uid"),
            {"uid": tenant.user_id},
        )
        conv_ids = [str(r.id) for r in rows]
    deleted = 0
    for conv_id in conv_ids:
        await redis.clear_session(conv_id)
        deleted += 1
    logger.info("Logout", user_id=tenant.user_id, sessions_deleted=deleted)
    return {"message": "Logout effettuato", "sessions_deleted": deleted}

