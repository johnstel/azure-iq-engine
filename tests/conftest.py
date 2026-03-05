"""
Shared pytest fixtures for Azure IQ Engine tests.
"""

import pytest

from src.api.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache on get_settings before and after every test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
