from __future__ import annotations
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from app.api.deps import CurrentTenant
from app.services.tenant_service import provision_tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])

class TenantCreate(BaseModel):
    slug: str
    display_name: str
    plan: str = "starter"
    admin_email: str | None = None
    admin_password: str | None = None

class TenantResponse(BaseModel):
    tenant_id: str
    slug: str
    plan: str
    admin_user_id: str | None = None

def _require_superadmin(tenant: CurrentTenant) -> None:
    if tenant.user_role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato ai superadmin",
        )

@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    tenant: CurrentTenant,
) -> TenantResponse:
    _require_superadmin(tenant)
    result = await provision_tenant(
        slug=body.slug,
        display_name=body.display_name,
        plan=body.plan,
        admin_email=body.admin_email,
        admin_password=body.admin_password,
    )
    return TenantResponse(**result)

@router.get("")
async def list_tenants(tenant: CurrentTenant) -> list[dict]:
    _require_superadmin(tenant)
    from app.db.sqlserver import tenant_db
    async with tenant_db._async_factory() as session:
        rows = await session.execute(
            text("""
                SELECT id, slug, display_name, plan, is_active, created_at
                FROM shared.tenants
                ORDER BY created_at DESC
            """)
        )
        return [ dict(r._mapping) for r in rows ]

@router.patch("/{slug}/disable")
async def disable_tenant(slug: str, tenant: CurrentTenant) -> dict:
    _require_superadmin(tenant)
    from app.db.sqlserver import tenant_db
    async with tenant_db._async_factory() as session:
        await session.execute(
            text("UPDATE shared.tenants SET is_active = 0 WHERE slug = :slug"),
            {"slug": slug}
        )
        await session.commit()
    return { "message": f"Tenant {slug} disabilitato" }

