"""
Shared pytest fixtures for the Azure IQ Engine test suite.
"""

from collections.abc import Generator

import pytest


# ---------------------------------------------------------------------------
# Settings cache management
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_settings_cache() -> Generator[None, None, None]:
    """Clear the lru_cache on get_settings before and after every test."""
    try:
        from src.api.settings import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()
    except ImportError:
        yield
