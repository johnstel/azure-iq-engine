"""
Tests for the in-memory sliding-window rate limiter.
"""

from __future__ import annotations

import time

import pytest

from src.api.rate_limit import RateLimitRule, _SlidingWindow


# ── _SlidingWindow unit tests ─────────────────────────────────────────────────

class TestSlidingWindow:
    def test_first_request_allowed(self):
        window = _SlidingWindow(window_seconds=60)
        allowed, remaining = window.allow(time.monotonic(), limit=5)
        assert allowed is True
        assert remaining == 4

    def test_request_up_to_limit_allowed(self):
        window = _SlidingWindow(window_seconds=60)
        now = time.monotonic()
        for _ in range(3):
            allowed, _ = window.allow(now, limit=3)
            assert allowed is True

    def test_request_over_limit_denied(self):
        window = _SlidingWindow(window_seconds=60)
        now = time.monotonic()
        for _ in range(3):
            window.allow(now, limit=3)
        allowed, remaining = window.allow(now, limit=3)
        assert allowed is False
        assert remaining == 0

    def test_expired_timestamps_purged(self):
        """Requests older than window_seconds should not count against the limit."""
        window = _SlidingWindow(window_seconds=1)
        past = time.monotonic() - 2  # 2 seconds ago — outside the 1-second window
        # Manually inject an old timestamp
        window._timestamps.append(past)
        # Even though we have one old timestamp, it should be purged
        allowed, remaining = window.allow(time.monotonic(), limit=1)
        assert allowed is True

    def test_remaining_decreases(self):
        window = _SlidingWindow(window_seconds=60)
        now = time.monotonic()
        _, r1 = window.allow(now, limit=5)
        _, r2 = window.allow(now, limit=5)
        assert r1 == 4
        assert r2 == 3


# ── RateLimitRule ─────────────────────────────────────────────────────────────

class TestRateLimitRule:
    def test_max_requests_equals_rpm(self):
        rule = RateLimitRule(path_prefix="/api/query", rpm=30)
        assert rule.max_requests() == 30

    def test_default_window_seconds(self):
        rule = RateLimitRule(path_prefix="/api/query", rpm=10)
        assert rule.window_seconds == 60


# ── Rate limit middleware via HTTP ────────────────────────────────────────────

def test_rate_limit_allows_requests_under_limit(client):
    """Requests within the rpm limit should return 200 from /health (no rule)."""
    for _ in range(5):
        resp = client.get("/health")
        assert resp.status_code == 200


def test_rate_limit_headers_present_on_query(client):
    """X-RateLimit-Limit and X-RateLimit-Remaining must appear on /api/query responses."""
    from unittest.mock import AsyncMock, patch

    with (
        patch("src.api.main._search_index", new_callable=AsyncMock, return_value=[]),
        patch("src.api.main._call_openai", new_callable=AsyncMock, return_value=("ok", 0)),
    ):
        resp = client.post("/api/query", json={"question": "What is Fabric IQ?"})

    assert resp.status_code == 200
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers


def test_rate_limit_exceeded_returns_429():
    """When rpm=1, the second request in the same window must get 429."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.rate_limit import RateLimitMiddleware, RateLimitRule

    tight_app = FastAPI()
    tight_app.add_middleware(
        RateLimitMiddleware,
        rules=[RateLimitRule(path_prefix="/api/query", rpm=1)],
    )

    @tight_app.post("/api/query")
    async def _query():
        return {"ok": True}

    with TestClient(tight_app) as tc:
        r1 = tc.post("/api/query")
        r2 = tc.post("/api/query")

    assert r1.status_code == 200
    assert r2.status_code == 429
    assert r2.json()["detail"] == "Rate limit exceeded. Please slow down."


def test_rate_limit_retry_after_header_on_429():
    """The Retry-After header must be set on 429 responses."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.rate_limit import RateLimitMiddleware, RateLimitRule

    tight_app = FastAPI()
    tight_app.add_middleware(
        RateLimitMiddleware,
        rules=[RateLimitRule(path_prefix="/probe", rpm=1, window_seconds=60)],
    )

    @tight_app.get("/probe")
    async def _probe():
        return {"ok": True}

    with TestClient(tight_app) as tc:
        tc.get("/probe")       # allowed
        resp = tc.get("/probe")  # denied

    assert resp.status_code == 429
    assert "retry-after" in resp.headers


def test_unmatched_path_passes_through():
    """Paths not matching any rule are never rate-limited."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.rate_limit import RateLimitMiddleware, RateLimitRule

    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        rules=[RateLimitRule(path_prefix="/api/limited", rpm=1)],
    )

    @app.get("/api/unlimited")
    async def _unlimited():
        return {"ok": True}

    with TestClient(app) as tc:
        for _ in range(10):
            assert tc.get("/api/unlimited").status_code == 200
