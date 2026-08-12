import json
import logging
from typing import Optional, Any
import redis.asyncio as redis
from app.config import settings

logger = logging.getLogger(__name__)

class CacheManager:
    """Redis-based cache manager for query result caching."""

    def __init__(self):
        self.redis = None

    async def connect(self):
        candidate = redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await candidate.ping()
            self.redis = candidate
            logger.info("Redis connected")
        except Exception as error:
            # Redis improves distribution and caching but must not prevent a
            # local/demo process from starting.
            self.redis = None
            await candidate.aclose()
            logger.warning("Redis unavailable; using graceful local fallbacks: %s", error)

    async def get(self, key: str) -> Optional[Any]:
        try:
            value = await self.redis.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 300):
        try:
            await self.redis.setex(key, ttl, json.dumps(value, default=str))
        except Exception as e:
            logger.warning(f"Cache set error: {e}")

    async def delete(self, key: str):
        try:
            await self.redis.delete(key)
        except Exception as e:
            logger.warning(f"Cache delete error: {e}")
