"""
conftest.py — shared fixtures and dependency overrides for CUSTOS test suite.

Key design: the FastAPI app holds a global rate_limiter singleton.
We override it per-test via FastAPI's dependency_overrides so each test
starts with a clean, known-quota limiter. This prevents order-dependent flakiness.
"""

import pytest
from fastapi.testclient import TestClient

import main as app_module
from custos.rate_limiter import QuotaConfig, RateLimiter

# Default quota matching the production singleton in main.py
DEFAULT_QUOTA = QuotaConfig(
    requests_per_minute=60,
    requests_per_hour=1000,
    tokens_per_minute=100_000,
)


def _fresh_limiter() -> RateLimiter:
    """Return a brand-new RateLimiter with the default client registered."""
    rl = RateLimiter()
    rl.register("default", DEFAULT_QUOTA)
    return rl


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Replace the app's rate_limiter singleton before every test,
    and restore it after. Works for both unit tests and API tests.
    """
    fresh = _fresh_limiter()
    original = app_module.rate_limiter
    app_module.rate_limiter = fresh
    yield fresh
    app_module.rate_limiter = original


@pytest.fixture
def client(reset_rate_limiter):
    """TestClient with a fresh rate limiter already in place."""
    from main import app
    return TestClient(app)
