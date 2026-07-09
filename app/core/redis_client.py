from __future__ import annotations
import json
from functools import lru_cache
from typing import Any
import redis.asyncio as aioredis
from loguru import logger

@lru_cache(maxsize=1)
def get_redis() -> aioredis.Redis:
    from app.core.settings import get_settings
    settings = get_settings()
    logger.info("Connessione Redis", url=settings.redis_url)
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )

@lru_cache(maxsize=1)
def get_cache_redis() -> aioredis.Redis:
    from app.core.settings import get_settings
    settings = get_settings()
    return aioredis.from_url(
        settings.redis_cache_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )

class TenantRedis:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._redis = get_redis()
        self._cache = get_cache_redis()

    def _key(self, *parts: str) -> str:
        return f"tenant:{self.tenant_id}:" + ":".join(parts)

    async def get_session(self, session_id: str) -> list[dict]:
        key = self._key("session", session_id)
        raw = await self._redis.lrange(key, 0, -1)
        return [ json.loads(m) for m in raw ]

    async def append_message(
        self,
        session_id: str,
        message: dict,
        max_turns: int = 10,
    ) -> None:
        from app.core.settings import get_settings
        settings = get_settings()
        key = self._key("session", session_id)
        ttl = settings.cache_session_ttl_seconds
        pipe = self._redis.pipeline()
        pipe.rpush(key, json.dumps(message, ensure_ascii=False))
        pipe.ltrim(key, -(max_turns * 2), -1)
        pipe.expire(key, ttl)
        await pipe.execute()

    async def clear_session(self, session_id: str) -> None:
        await self._redis.delete(self._key("session", session_id))

    async def get_query_cache(self, query_hash: str) -> str | None:
        return await self._cache.get(self._key("cache", "query", query_hash))

    async def set_query_cache(
        self,
        query_hash: str,
        response: str,
        ttl: int | None = None,
    ) -> None:
        from app.core.settings import get_settings
        settings = get_settings()
        key = self._key("cache", "query", query_hash)
        await self._cache.setex(key,  ttl or settings.cache_query_ttl_seconds,  response)

    async def invalidate_query_cache(self) -> int:
        pattern = self._key("cache", "query", "*")
        keys = await self._cache.keys(pattern)
        if keys:
            await self._cache.delete(*keys)
        return len(keys)

    async def check_rate_limit(
        self,
        user_id: str,
        limit: int | None = None,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        from app.core.settings import get_settings
        settings = get_settings()
        max_requests = limit or settings.rate_limit_requests_per_minute
        key = self._key("ratelimit", user_id)
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        count = results[0]
        return ( count <= max_requests, count )

    async def set_job_status(
        self,
        job_id: str,
        status: dict,
        ttl: int = 86400,
    ) -> None:
        key = self._key("job", job_id)
        await self._redis.setex(key, ttl, json.dumps(status))

    async def get_job_status(self, job_id: str) -> dict | None:
        raw = await self._redis.get( self._key("job", job_id) )
        return json.loads(raw) if raw else None

    async def flush_tenant(self) -> int:
        pattern = f"tenant:{self.tenant_id}:*"
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor, match=pattern, count=100
            )
            if keys:
                await self._redis.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break

        cursor = 0
        while True:
            cursor, keys = await self._cache.scan(
                cursor=cursor, match=pattern, count=100
            )
            if keys:
                await self._cache.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        logger.info(f"Flush tenant Redis completato", tenant=self.tenant_id, deleted=deleted)
        return deleted

    @staticmethod
    async def ping() -> bool:
        try:
            client = get_redis()
            return await client.ping()
        except Exception as e:
            logger.error(f"Redis ping fallito: {e}")
            return False

