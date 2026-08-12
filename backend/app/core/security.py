"""Small, dependency-free security helpers shared by API routes."""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import logging
import re
import time
import math
from typing import Deque

from fastapi import HTTPException, Request

NAMESPACE_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def validate_namespace(namespace: str | None) -> str:
    value = (namespace or "default").strip()
    if not NAMESPACE_PATTERN.fullmatch(value):
        raise HTTPException(400, "Namespace must use 1-64 letters, numbers, hyphens, or underscores")
    return value


def client_identifier(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    return forwarded_for.split(",")[0].strip() or (request.client.host if request.client else "unknown")


class SlidingWindowRateLimiter:
    """Best-effort per-process rate limiting. Use a gateway for multi-instance limits."""

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        window = self._requests[key]
        while window and window[0] <= now - self.window_seconds:
            window.popleft()
        if len(window) >= self.limit:
            raise HTTPException(429, "Too many requests. Please try again shortly.")
        window.append(now)


class RateLimitExceeded(HTTPException):
    """429 that always communicates exactly when a client may retry."""

    def __init__(self, retry_after: int):
        super().__init__(
            status_code=429,
            detail="Rate limit exceeded. Please retry shortly.",
            headers={"Retry-After": str(max(1, retry_after))},
        )


class ResilientRateLimiter:
    """Redis token bucket with a bounded, process-local fallback."""

    # One Lua script makes refill + consume atomic for every app instance.
    _TOKEN_BUCKET = """
    local raw = redis.call('GET', KEYS[1])
    local capacity = tonumber(ARGV[2])
    local now = tonumber(ARGV[1])
    local refill = tonumber(ARGV[3])
    local ttl = tonumber(ARGV[4])
    local tokens = capacity
    local last = now
    if raw then
      local separator = string.find(raw, ':')
      if separator then
        tokens = tonumber(string.sub(raw, 1, separator - 1)) or capacity
        last = tonumber(string.sub(raw, separator + 1)) or now
      end
    end
    tokens = math.min(capacity, tokens + math.max(0, now - last) * refill)
    if tokens < 1 then
      redis.call('SETEX', KEYS[1], ttl, tostring(tokens) .. ':' .. tostring(now))
      return {0, math.ceil((1 - tokens) / refill)}
    end
    tokens = tokens - 1
    redis.call('SETEX', KEYS[1], ttl, tostring(tokens) .. ':' .. tostring(now))
    return {1, 0}
    """

    def __init__(self, redis_client=None, window_seconds: int = 60, clock=time.monotonic):
        self.redis = redis_client
        self.window_seconds = window_seconds
        self.clock = clock
        self._requests: dict[str, Deque[float]] = defaultdict(deque)

    async def check(self, key: str, limit: int) -> None:
        if self.redis is not None:
            try:
                counter_key = f"rate-limit:{key}"
                allowed, retry_after = await self.redis.eval(
                    self._TOKEN_BUCKET, 1, counter_key, time.time(), limit,
                    limit / self.window_seconds, self.window_seconds * 2,
                )
                if not allowed:
                    raise RateLimitExceeded(int(retry_after) or 1)
                return
            except RateLimitExceeded:
                raise
            except Exception as error:
                # Redis should improve distribution, never become an availability dependency.
                logging.getLogger(__name__).warning("Redis rate limiter unavailable; using in-memory fallback: %s", error)
                self.redis = None

        now = self.clock()
        window = self._requests[key]
        while window and window[0] <= now - self.window_seconds:
            window.popleft()
        if len(window) >= limit:
            retry_after = math.ceil(window[0] + self.window_seconds - now)
            raise RateLimitExceeded(retry_after)
        window.append(now)
