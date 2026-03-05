"""
Redis caching layer for Azure IQ Engine.

Provides two cache tiers:
  - Search results  — TTL: cache_search_ttl (default 1 hour)
  - LLM responses   — TTL: cache_llm_ttl    (default 4 hours)

Cache keys are SHA256 hashes of the normalised query parameters.
Graceful degradation: all cache operations are no-ops when Redis is
not configured or unreachable.

Cache invalidation:
  call ``invalidate_all()`` after a successful ingestion run to flush
  stale search-result and LLM-response entries.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Key-space prefixes so different cache tiers never collide.
_PREFIX_SEARCH = "iqe:search:"
_PREFIX_LLM = "iqe:llm:"

# Module-level client — initialised once in the FastAPI lifespan.
_redis_client: Any | None = None


# ── Lifecycle ──────────────────────────────────────────────────────────────────

async def init_cache(redis_url: str) -> None:
    """
    Initialise the async Redis client.

    Safe to call with an empty *redis_url* — caching will simply be disabled.
    """
    global _redis_client  # noqa: PLW0603

    if not redis_url:
        logger.info("REDIS_URL not set — caching disabled")
        return

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        # Verify connectivity
        await client.ping()
        _redis_client = client
        logger.info("Redis cache connected: %s", redis_url.split("@")[-1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable — caching disabled: %s", exc)
        _redis_client = None


async def close_cache() -> None:
    """Close the Redis connection on application shutdown."""
    global _redis_client  # noqa: PLW0603

    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error closing Redis connection: %s", exc)
        finally:
            _redis_client = None


# ── Key helpers ────────────────────────────────────────────────────────────────

def make_search_key(
    query: str,
    *,
    iq_layer: str | None = None,
    source_type: str | None = None,
    top_k: int = 5,
) -> str:
    """
    Deterministic cache key for a search-index request.

    The key encodes the normalised query + all filter dimensions that affect
    the result set.
    """
    parts = [
        query.strip().lower(),
        iq_layer or "",
        source_type or "",
        str(top_k),
    ]
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"{_PREFIX_SEARCH}{digest}"


def make_llm_key(system_prompt: str, user_prompt: str) -> str:
    """
    Deterministic cache key for an LLM call.

    Keyed on the full prompt pair so that different search results always
    produce a distinct LLM key even for the same question.
    """
    digest = hashlib.sha256(
        (system_prompt + "\x00" + user_prompt).encode()
    ).hexdigest()
    return f"{_PREFIX_LLM}{digest}"


def make_query_key(
    question: str,
    agent: str,
    iq_layers: list[str] | None,
    top_k: int,
) -> str:
    """
    Top-level cache key for the /api/query endpoint.

    Encodes all parameters that affect the final response.
    """
    parts = [
        question.strip().lower(),
        agent,
        ",".join(sorted(iq_layers or [])),
        str(top_k),
    ]
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"{_PREFIX_LLM}{digest}"


# ── Get / Set helpers ──────────────────────────────────────────────────────────

async def cache_get(key: str) -> Any | None:
    """
    Retrieve a cached value.

    Returns the deserialised Python object or ``None`` on a miss or error.
    """
    if _redis_client is None:
        return None

    try:
        raw = await _redis_client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache GET error for key %s: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    """
    Store a value in the cache with the given TTL (seconds).

    Silently ignores errors so a Redis outage never breaks the API.
    """
    if _redis_client is None:
        return

    try:
        await _redis_client.setex(key, ttl, json.dumps(value))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache SET error for key %s: %s", key, exc)


# ── Invalidation ───────────────────────────────────────────────────────────────

async def invalidate_all() -> int:
    """
    Delete all IQ Engine cache entries (search + LLM tiers).

    Returns the number of keys deleted. Called after a successful ingestion
    run so that stale corpus-derived responses are evicted.
    """
    if _redis_client is None:
        return 0

    deleted = 0
    try:
        for prefix in (_PREFIX_SEARCH, _PREFIX_LLM):
            cursor = 0
            pattern = f"{prefix}*"
            while True:
                cursor, keys = await _redis_client.scan(cursor, match=pattern, count=200)
                if keys:
                    deleted += await _redis_client.delete(*keys)
                if cursor == 0:
                    break
        logger.info("Cache invalidated — %d keys deleted", deleted)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache invalidation error: %s", exc)

    return deleted
