"""
In-memory sliding-window rate limiter — FastAPI middleware.

No Redis dependency for MVP. State lives in-process; reset on restart.
For production: replace with Redis-backed sliding window or Azure API Management.

Usage:
    app.add_middleware(
        RateLimitMiddleware,
        rules=[
            RateLimitRule(path_prefix="/api/query", rpm=30),
            RateLimitRule(path_prefix="/api/research", rpm=10),
        ],
    )
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


@dataclass
class RateLimitRule:
    """A single rate-limit rule tied to a URL path prefix."""

    path_prefix: str
    rpm: int  # max requests per minute
    window_seconds: int = 60

    def max_requests(self) -> int:
        return self.rpm


class _SlidingWindow:
    """Thread-safe sliding-window counter for a single IP + path rule."""

    __slots__ = ("_timestamps", "_window")

    def __init__(self, window_seconds: int) -> None:
        self._timestamps: deque[float] = deque()
        self._window = window_seconds

    def allow(self, now: float, limit: int) -> tuple[bool, int]:
        """
        Returns (allowed, remaining).
        Purges expired timestamps before checking.
        """
        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

        remaining = limit - len(self._timestamps)
        if remaining <= 0:
            return False, 0

        self._timestamps.append(now)
        return True, remaining - 1


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter applied per IP address.

    Rules are evaluated in declaration order; the first matching prefix wins.
    Paths not matched by any rule pass through unrestricted.
    """

    def __init__(
        self,
        app: ASGIApp,
        rules: list[RateLimitRule] | None = None,
    ) -> None:
        super().__init__(app)
        self._rules: list[RateLimitRule] = rules or []
        # { (ip, path_prefix) → SlidingWindow }
        self._windows: dict[tuple[str, str], _SlidingWindow] = defaultdict(
            lambda: _SlidingWindow(60)  # placeholder; overridden below
        )
        # Pre-build with correct window per rule prefix
        self._rule_map: dict[str, RateLimitRule] = {r.path_prefix: r for r in self._rules}

    def _get_client_ip(self, request: Request) -> str:
        """Extract real IP, honouring X-Forwarded-For when set."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _match_rule(self, path: str) -> RateLimitRule | None:
        for rule in self._rules:
            if path.startswith(rule.path_prefix):
                return rule
        return None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rule = self._match_rule(request.url.path)
        if rule is None:
            return await call_next(request)

        ip = self._get_client_ip(request)
        key = (ip, rule.path_prefix)

        # Lazily create the window with the correct window_seconds
        if key not in self._windows:
            self._windows[key] = _SlidingWindow(rule.window_seconds)

        now = time.monotonic()
        allowed, remaining = self._windows[key].allow(now, rule.max_requests())

        if not allowed:
            retry_after = rule.window_seconds
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please slow down.",
                    "limit": rule.max_requests(),
                    "window_seconds": rule.window_seconds,
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rule.max_requests()),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(rule.max_requests())
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
