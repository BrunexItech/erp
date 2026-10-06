"""Fixed-window rate limiting on Redis, for the endpoints an attacker would
hammer: login (password guessing) and forgot-password (inbox flooding).

Fails open: if Redis is unreachable the request is allowed. Locking every user
out because a cache is down would be a worse failure than briefly losing the
limiter.
"""

from __future__ import annotations

import logging

import redis.asyncio as redis
from fastapi import HTTPException, Request, status

from app.core.config import settings

log = logging.getLogger(__name__)
_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
    return _client


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


async def hit(key: str, *, limit: int, window_seconds: int) -> None:
    """Count one attempt against `key`; raise 429 once over `limit` per window."""
    if settings.testing:
        return
    try:
        client = _redis()
        count = await client.incr(f"rl:{key}")
        if count == 1:
            await client.expire(f"rl:{key}", window_seconds)
        ttl = await client.ttl(f"rl:{key}")
    except Exception as exc:
        log.warning("rate limiter unavailable (%s) — allowing request", exc)
        return
    if count > limit:
        minutes = max(1, (ttl + 59) // 60)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"too many attempts — try again in about {minutes} minute(s)",
        )
