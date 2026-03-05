"""
Tests for the Redis caching layer (src/api/cache.py).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api import cache as cache_module
from src.api.cache import (
    cache_get,
    cache_set,
    close_cache,
    init_cache,
    invalidate_all,
    make_llm_key,
    make_query_key,
    make_search_key,
)


# ── Key-generation tests ───────────────────────────────────────────────────────

def test_make_search_key_deterministic():
    k1 = make_search_key("What is Fabric IQ?", iq_layer="fabric-iq", top_k=5)
    k2 = make_search_key("What is Fabric IQ?", iq_layer="fabric-iq", top_k=5)
    assert k1 == k2
    assert k1.startswith("iqe:search:")


def test_make_search_key_varies_with_params():
    base = make_search_key("query", top_k=5)
    with_layer = make_search_key("query", iq_layer="fabric-iq", top_k=5)
    with_top = make_search_key("query", top_k=10)
    assert base != with_layer
    assert base != with_top


def test_make_search_key_case_insensitive():
    k1 = make_search_key("What is Work IQ?")
    k2 = make_search_key("what is work iq?")
    assert k1 == k2


def test_make_llm_key_deterministic():
    k1 = make_llm_key("system", "user prompt")
    k2 = make_llm_key("system", "user prompt")
    assert k1 == k2
    assert k1.startswith("iqe:llm:")


def test_make_llm_key_varies_with_content():
    k1 = make_llm_key("system A", "user")
    k2 = make_llm_key("system B", "user")
    assert k1 != k2


def test_make_query_key_deterministic():
    k1 = make_query_key("How does Foundry IQ work?", "iq-architect", ["foundry-iq"], 5)
    k2 = make_query_key("How does Foundry IQ work?", "iq-architect", ["foundry-iq"], 5)
    assert k1 == k2
    assert k1.startswith("iqe:llm:")


def test_make_query_key_layer_order_independent():
    k1 = make_query_key("q", "agent", ["fabric-iq", "work-iq"], 5)
    k2 = make_query_key("q", "agent", ["work-iq", "fabric-iq"], 5)
    assert k1 == k2


# ── Cache operations (no Redis) ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_cache_client():
    """Ensure the module-level client is None before and after each test."""
    original = cache_module._redis_client
    cache_module._redis_client = None
    yield
    cache_module._redis_client = original


async def test_cache_get_returns_none_when_no_client():
    result = await cache_get("some:key")
    assert result is None


async def test_cache_set_is_noop_when_no_client():
    # Should not raise
    await cache_set("some:key", {"data": 1}, 60)


async def test_invalidate_all_returns_zero_when_no_client():
    deleted = await invalidate_all()
    assert deleted == 0


async def test_init_cache_with_empty_url():
    await init_cache("")
    assert cache_module._redis_client is None


async def test_close_cache_no_client():
    cache_module._redis_client = None
    await close_cache()  # should not raise


# ── Cache operations (mocked Redis) ───────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """Provide a mock async Redis client wired into the cache module."""
    client = AsyncMock()
    client.ping = AsyncMock(return_value=True)
    cache_module._redis_client = client
    yield client
    cache_module._redis_client = None


async def test_cache_get_hit(mock_redis):
    payload = {"answer": "42", "tokens": 100}
    mock_redis.get = AsyncMock(return_value=json.dumps(payload))

    result = await cache_get("iqe:llm:abc123")
    assert result == payload
    mock_redis.get.assert_awaited_once_with("iqe:llm:abc123")


async def test_cache_get_miss(mock_redis):
    mock_redis.get = AsyncMock(return_value=None)
    result = await cache_get("iqe:llm:missing")
    assert result is None


async def test_cache_get_handles_error(mock_redis):
    mock_redis.get = AsyncMock(side_effect=Exception("connection lost"))
    result = await cache_get("iqe:llm:error")
    assert result is None


async def test_cache_set_calls_setex(mock_redis):
    value = {"foo": "bar"}
    await cache_set("iqe:search:xyz", value, 3600)
    mock_redis.setex.assert_awaited_once_with("iqe:search:xyz", 3600, json.dumps(value))


async def test_cache_set_handles_error(mock_redis):
    mock_redis.setex = AsyncMock(side_effect=Exception("write error"))
    await cache_set("key", {"v": 1}, 60)  # should not raise


async def test_invalidate_all_deletes_keys(mock_redis):
    # Two search keys deleted in first delete call, one LLM key in second
    search_keys = ["iqe:search:a", "iqe:search:b"]
    llm_keys = ["iqe:llm:c"]

    scan_results = [
        (0, search_keys),   # search prefix scan complete
        (0, llm_keys),      # llm prefix scan complete
    ]
    mock_redis.scan = AsyncMock(side_effect=scan_results)
    mock_redis.delete = AsyncMock(side_effect=[2, 1])

    deleted = await invalidate_all()
    assert deleted == 3  # 2 search keys + 1 llm key


async def test_invalidate_all_handles_error(mock_redis):
    mock_redis.scan = AsyncMock(side_effect=Exception("scan failed"))
    deleted = await invalidate_all()
    assert deleted == 0


async def test_init_cache_ping_failure_disables_client():
    with patch("redis.asyncio.from_url") as mock_from_url:
        client = AsyncMock()
        client.ping = AsyncMock(side_effect=Exception("refused"))
        mock_from_url.return_value = client

        await init_cache("redis://localhost:6379")
        assert cache_module._redis_client is None


async def test_close_cache_calls_aclose(mock_redis):
    await close_cache()
    mock_redis.aclose.assert_awaited_once()
    assert cache_module._redis_client is None
