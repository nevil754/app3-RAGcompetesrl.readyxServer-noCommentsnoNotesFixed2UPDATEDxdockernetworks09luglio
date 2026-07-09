from __future__ import annotations
from loguru import logger
from sqlalchemy import text
from app.workers.celery_app import celery_app

@celery_app.task(
    name="app.workers.cleanup_tasks.purge_tenant",
    acks_late=True,
)
def purge_tenant(tenant_id: str, tenant_slug: str) -> dict:
    import asyncio
    from app.db.sqlserver import tenant_db
    from app.core.vectorstore import adelete_tenant_collections
    from app.core.redis_client import TenantRedis

    logger.warning(f"Purge tenant avviato: {tenant_slug}")
    loop = asyncio.new_event_loop()
    loop.run_until_complete( adelete_tenant_collections(tenant_slug) )
    loop.close()
    loop = asyncio.new_event_loop()
    redis = TenantRedis( tenant_id = tenant_id )
    deleted_keys = loop.run_until_complete( redis.flush_tenant() )
    loop.close()
    schema_name = "tenant_" + tenant_slug.replace("-", "_")
    with tenant_db._sync_factory() as session:
        session.execute(
            text("UPDATE shared.tenants SET is_active = 0 WHERE slug = :slug"),
            {"slug": tenant_slug}
        )
        session.execute(text(f"DROP SCHEMA IF EXISTS [{schema_name}]"))
        session.commit()

    logger.info(
        "Purge tenant completato",
        tenant=tenant_slug,
        redis_keys_deleted=deleted_keys,
    )
    return {"status": "purged", "tenant": tenant_slug}

@celery_app.task(
    name="app.workers.cleanup_tasks.expire_sessions",
    acks_late=True,
)
def expire_sessions() -> dict:
    import asyncio
    from app.core.redis_client import get_redis

    async def _cleanup():
        client = get_redis()

        cursor = 0
        fixed = 0
        while True:
            cursor, keys = await client.scan( cursor=cursor, match="tenant:*:session:*", count=200 )
            for key in keys:
                ttl = await client.ttl(key)
                if ttl == -1:
                    await client.expire(key, 86400)
                    fixed += 1
            if cursor == 0:
                break
        return fixed

    loop = asyncio.new_event_loop()
    fixed = loop.run_until_complete( _cleanup() )
    loop.close()
    logger.info(f"Session cleanup: {fixed} chiavi senza TTL corrette")
    return {"fixed_keys": fixed}

