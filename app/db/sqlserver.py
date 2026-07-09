from __future__ import annotations
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import AsyncGenerator, Generator
from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

class TenantDB:
    def __init__(self):
        self._sync_factory = sessionmaker(
            bind= get_sync_engine(),
            autocommit= False,
            autoflush= False,
        )
        self._async_factory = async_sessionmaker(
            bind=get_async_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    @contextmanager
    def get_session(self, tenant_slug: str) -> Generator[Session, None, None]:
        session = self._sync_factory()
        impersonated = False
        try:
            self._set_schema_sync(session, tenant_slug)
            impersonated = True
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            if impersonated:
                try:
                    session.execute(text("REVERT"))
                    session.commit()
                except Exception:
                    pass
            session.close()

    @asynccontextmanager
    async def aget_session(
        self, tenant_slug: str
    ) -> AsyncGenerator[AsyncSession, None]:
        async with self._async_factory() as session:
            impersonated = False
            try:
                await self._set_schema_async(session, tenant_slug)
                impersonated = True
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                if impersonated:
                    try:
                        await session.execute(text("REVERT"))
                        await session.commit()
                    except Exception:
                        pass

    def _set_schema_sync(self, session: Session, tenant_slug: str) -> None:
        schema_name = _slug_to_schema(tenant_slug)
        result = session.execute(
            text("SELECT 1 FROM sys.schemas WHERE name = :schema"),
            {"schema": schema_name}
        ).fetchone()
        if not result:
            raise ValueError(
                f"Schema tenant '{schema_name}' non trovato. "
                f"Eseguire sp_provision_tenant prima."
            )
        user_name = _slug_to_user(tenant_slug)
        session.execute(text(f"EXECUTE AS USER = N'{user_name}'"))

    async def _set_schema_async(
        self, session: AsyncSession, tenant_slug: str
    ) -> None:
        schema_name = _slug_to_schema(tenant_slug)
        result = await session.execute(
            text("SELECT 1 FROM sys.schemas WHERE name = :schema"),
            {"schema": schema_name}
        )
        if not result.fetchone():
            raise ValueError(
                f"Schema tenant '{schema_name}' non trovato."
            )
        user_name = _slug_to_user(tenant_slug)
        await session.execute(text(f"EXECUTE AS USER = N'{user_name}'"))

    async def provision_tenant(
        self,
        slug: str,
        display_name: str,
        plan: str = "starter",
    ) -> None:
        async with self._async_factory() as session:
            try:
                await session.execute(
                    text("""
                        EXEC shared.sp_provision_tenant
                            @slug = :slug,
                            @display_name = :display_name,
                            @plan = :plan
                    """),
                    {"slug": slug, "display_name": display_name, "plan": plan}
                )
                await session.commit()
                logger.info(
                    "Tenant provisionato",
                    slug=slug,
                    schema=_slug_to_schema(slug),
                )
            except Exception as e:
                await session.rollback()
                logger.error(f"Errore provisioning tenant {slug}: {e}")
                raise

    @staticmethod
    async def ping() -> bool:
        try:
            engine = get_async_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"SQL Server ping fallito: {e}")
            return False

def _slug_to_schema(slug: str) -> str:
    return "tenant_" + slug.replace("-", "_").lower()

def _slug_to_user(slug: str) -> str:
    return "usr_" + _slug_to_schema(slug)

tenant_db = TenantDB()

@lru_cache(maxsize=1)
def get_sync_engine():
    from app.core.settings import get_settings
    settings = get_settings()
    engine = create_engine(
        settings.sqlserver_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.app_debug,
    )
    logger.info("Engine SQL Server sincrono creato")
    return engine

@lru_cache(maxsize=1)
def get_async_engine():
    from app.core.settings import get_settings
    settings = get_settings()

    async_url = settings.sqlserver_url.replace(
        "mssql+pyodbc", "mssql+aioodbc"
    )
    engine = create_async_engine(
        async_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.app_debug,
    )
    logger.info("Engine SQL Server asincrono creato")
    return engine

