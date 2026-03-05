"""
Shared pytest fixtures for the Azure IQ Engine test suite.

All external Azure services are mocked — no real API calls are made in tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.settings import Settings, get_settings


# ── Settings override ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache on get_settings() before every test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def mock_settings(monkeypatch) -> Settings:
    """
    Provide a Settings instance with no Azure credentials set.
    This ensures the app degrades gracefully instead of hitting real services.
    """
    monkeypatch.setenv("FOUNDRY_BASE_URL", "")
    monkeypatch.setenv("FOUNDRY_KEY", "")
    monkeypatch.setenv("SEARCH_ENDPOINT", "")
    monkeypatch.setenv("SEARCH_API_KEY", "")
    monkeypatch.setenv("BING_API_KEY", "")
    get_settings.cache_clear()
    return get_settings()


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest.fixture()
def client(mock_settings) -> TestClient:
    """
    Return an httpx-based TestClient for the FastAPI app.

    Settings cache is cleared and environment variables are set to empty
    so no real Azure calls are attempted.
    """
    from src.api.main import app

    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc
