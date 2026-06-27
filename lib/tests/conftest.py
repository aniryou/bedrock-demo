"""Shared test fixtures."""

import pytest

import agent_kit.config as config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Each test gets a fresh, env-driven Config (it is lru_cached)."""
    config.get_config.cache_clear()
    yield
    config.get_config.cache_clear()
