"""
Shared pytest fixtures for the Azure IQ Engine test suite.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the settings LRU cache before and after every test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client() -> TestClient:
    """Return a synchronous FastAPI TestClient."""
    return TestClient(app, raise_server_exceptions=False)
