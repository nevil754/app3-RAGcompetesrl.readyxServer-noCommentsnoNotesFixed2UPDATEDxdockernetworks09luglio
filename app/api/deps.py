from __future__ import annotations
from typing import Annotated, AsyncGenerator
from fastapi import Depends, Header, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.redis_client import TenantRedis
from app.core.security import decode_access_token, extract_bearer_token, hash_api_key
from app.db.sqlserver import tenant_db

class TenantContext:
    def __init__(
        self,
        tenant_id: str,
        tenant_slug: str,
        user_id: str,
        user_role: str,
        user_email: str,
    ):
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.user_id = user_id
        self.user_role = user_role
        self.user_email = user_email

    @property
    def is_admin(self) -> bool:
        return self.user_role == "admin"

    @property
    def is_viewer(self) -> bool:
        return self.user_role == "viewer"

async def get_current_tenant(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> TenantContext:
    if authorization:
        token = extract_bearer_token(authorization)
        if token:
            payload = decode_access_token(token)
            if payload:
                return TenantContext(
                    tenant_id=payload.get("tenant_id", ""),
                    tenant_slug=payload.get("tenant_slug", ""),
                    user_id=payload.get("sub", ""),
                    user_role=payload.get("role", "user"),
                    user_email=payload.get("email", ""),
                )
    if x_api_key:
        context = await _validate_api_key(x_api_key)
        if context:
            return context
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token non valido o scaduto",
        headers={"WWW-Authenticate": "Bearer"},
    )

async def _validate_api_key(api_key: str) -> TenantContext | None:
    try:
        key_hash = hash_api_key(api_key)

        async with tenant_db._async_factory() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("""
                    SELECT
                        ak.tenant_id,
                        t.slug as tenant_slug,
                        ak.scopes
                    FROM shared.api_keys ak
                    JOIN shared.tenants t ON ak.tenant_id = t.id
                    WHERE ak.key_hash = :hash
                      AND ak.is_active = 1
                      AND (ak.expires_at IS NULL OR ak.expires_at > GETUTCDATE())
                """),
                {"hash": key_hash}
            )
            row = result.fetchone()
            if not row:
                return None
            await session.execute(
                text("UPDATE shared.api_keys SET last_used = GETUTCDATE() WHERE key_hash = :hash"),
                {"hash": key_hash}
            )
            await session.commit()
            return TenantContext(
                tenant_id=str(row.tenant_id),
                tenant_slug=row.tenant_slug,
                user_id=f"api_key_{key_hash[:8]}",
                user_role="api",
                user_email="",
            )
    except Exception as e:
        logger.error(f"Errore validazione API key: {e}")
        return None

async def get_db(
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
) -> AsyncGenerator[AsyncSession, None]:
    async with tenant_db.aget_session(tenant.tenant_slug) as session:
        yield session

def get_tenant_redis(
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
) -> TenantRedis:
    return TenantRedis(tenant_id=tenant.tenant_id)

async def require_admin(
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
) -> TenantContext:
    if not tenant.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato agli amministratori",
        )
    return tenant

CurrentTenant = Annotated[TenantContext, Depends(get_current_tenant)]
CurrentDB = Annotated[AsyncSession, Depends(get_db)]
CurrentRedis = Annotated[TenantRedis, Depends(get_tenant_redis)]
AdminOnly = Annotated[TenantContext, Depends(require_admin)]

