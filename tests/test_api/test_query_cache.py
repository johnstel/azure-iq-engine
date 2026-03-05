"""
Integration tests for the /api/query endpoint focusing on caching behaviour.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api import cache as cache_module
from src.api.main import app


@pytest.fixture(autouse=True)
def disable_cache():
    """Ensure the module-level Redis client is None for endpoint tests."""
    original = cache_module._redis_client
    cache_module._redis_client = None
    yield
    cache_module._redis_client = original


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_query_endpoint_miss_header(client):
    """When Redis is disabled the X-Cache header should be MISS."""
    with (
        patch("src.api.main._search_index", new=AsyncMock(return_value=[])),
        patch(
            "src.api.main._call_openai",
            new=AsyncMock(return_value=("stub answer", 10, False)),
        ),
    ):
        resp = client.post("/api/query", json={"question": "What is Fabric IQ?"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Cache") == "MISS"


def test_query_endpoint_hit_header(client):
    """When the LLM call returns a cache hit the X-Cache header should be HIT."""
    with (
        patch("src.api.main._search_index", new=AsyncMock(return_value=[])),
        patch(
            "src.api.main._call_openai",
            new=AsyncMock(return_value=("cached answer", 0, True)),
        ),
    ):
        resp = client.post("/api/query", json={"question": "What is Work IQ?"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Cache") == "HIT"
    data = resp.json()
    assert data["answer"] == "cached answer"
