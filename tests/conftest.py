"""
Shared pytest fixtures for the Azure IQ Engine test suite.
"""

from __future__ import annotations

import pytest

from src.api.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache on get_settings before and after every test.

    This ensures that environment-variable mutations in individual tests
    don't bleed into subsequent tests.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
