"""
Azure IQ Engine — Redis Cache Layer

Provides async Redis caching with graceful degradation.

If REDIS_URL is not set or the Redis server is unreachable, all methods
silently no-op so the application continues to function without caching.

Cache key generation:
    SHA256(normalise(query) + "|" + agent + "|" + serialised_filters)

TTL constants:
    TTL_SEARCH = 3 600 s  (1 hour)   — search/RAG results
    TTL_LLM    = 14 400 s (4 hours)  — LLM-synthesised responses
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# TTL constants exposed for callers
TTL_SEARCH: int = 3_600    # 1 hour  — search / RAG results
TTL_LLM: int = 14_400      # 4 hours — LLM-synthesised responses

# Module-level Redis client (lazily initialised)
_redis: Any = None
_redis_available: bool | None = None  # None = not yet tried


def _normalise_query(query: str) -> str:
    """Lowercase + collapse whitespace for stable cache keys."""
    return " ".join(query.lower().split())


def make_cache_key(
    query: str,
    *,
    agent: str = "",
    filters: dict[str, Any] | None = None,
) -> str:
    """
    Build a deterministic SHA-256 cache key.

    Parameters
    ----------
    query:
        The user query string.
    agent:
        The agent name selected for this request (may be empty string).
    filters:
        Arbitrary filter dict (e.g. ``{"iq_layer": "fabric-iq"}``).
    """
    serialised_filters = json.dumps(filters or {}, sort_keys=True)
    raw = f"{_normalise_query(query)}|{agent}|{serialised_filters}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _get_client() -> Any | None:
    """
    Return an initialised redis.asyncio client, or *None* when Redis is
    unavailable / not configured.
    """
    global _redis, _redis_available

    if _redis_available is False:
        return None  # Already failed; don't retry on every request

    if _redis is not None:
        return _redis

    # Lazy import so that the package is optional
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
    except ImportError:
        if _redis_available is None:
            logger.warning(
                "redis package not installed — caching disabled. "
                "Install with: pip install redis[hiredis]"
            )
        _redis_available = False
        return None

    from .settings import get_settings

    settings = get_settings()
    redis_url: str = getattr(settings, "redis_url", "") or ""

    if not redis_url:
        if _redis_available is None:
            logger.warning(
                "REDIS_URL not configured — caching disabled. "
                "Set REDIS_URL to enable query caching."
            )
        _redis_available = False
        return None

    try:
        client = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        # Verify connectivity
        await client.ping()
        _redis = client
        _redis_available = True
        logger.info("Redis cache connected: %s", redis_url.split("@")[-1])
        return _redis
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis connection failed (%s) — caching disabled", exc)
        _redis_available = False
        return None


async def get_cached(key: str) -> Any | None:
    """
    Retrieve a cached value by key.

    Returns the deserialised Python object, or *None* on cache miss / error.
    """
    client = await _get_client()
    if client is None:
        return None

    try:
        raw = await client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache GET failed for key %s: %s", key[:16], exc)
        return None


async def set_cached(key: str, value: Any, ttl: int = TTL_SEARCH) -> None:
    """
    Store *value* in the cache under *key* with the given TTL (seconds).

    Silently no-ops on any error.
    """
    client = await _get_client()
    if client is None:
        return

    try:
        serialised = json.dumps(value, default=str)
        await client.setex(key, ttl, serialised)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache SET failed for key %s: %s", key[:16], exc)


async def invalidate_pattern(pattern: str) -> int:
    """
    Delete all keys matching *pattern* (glob-style, e.g. ``"abc123*"``).

    Returns the number of keys deleted.  Returns 0 on error or when Redis
    is unavailable.
    """
    client = await _get_client()
    if client is None:
        return 0

    deleted = 0
    try:
        async for key in client.scan_iter(match=pattern, count=100):
            await client.delete(key)
            deleted += 1
        logger.info("Cache invalidated %d key(s) matching '%s'", deleted, pattern)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache invalidation failed for pattern '%s': %s", pattern, exc)

    return deleted
