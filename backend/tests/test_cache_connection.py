import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.utils.cache as cache_module
from app.utils.cache import CacheManager


class FailingRedis:
    closed = False

    async def ping(self):
        raise ConnectionError("offline")

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_cache_connect_degrades_cleanly_when_redis_is_unavailable(monkeypatch):
    client = FailingRedis()
    monkeypatch.setattr(cache_module.redis, "from_url", lambda *args, **kwargs: client)
    cache = CacheManager()

    await cache.connect()

    assert cache.redis is None
    assert client.closed


@pytest.mark.asyncio
async def test_cache_passes_upstash_tls_url_to_redis_client(monkeypatch):
    captured = {}

    class HealthyRedis:
        async def ping(self): pass

    monkeypatch.setattr(cache_module.settings, "REDIS_URL", "rediss://:token@global-upstash.example:6379")
    monkeypatch.setattr(cache_module.redis, "from_url", lambda url, **kwargs: captured.update(url=url, **kwargs) or HealthyRedis())
    cache = CacheManager()

    await cache.connect()

    assert captured["url"].startswith("rediss://")
    assert captured["decode_responses"] is True
    assert cache.redis is not None
