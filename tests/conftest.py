"""
conftest.py — shared fixtures for CUSTOS test suite.

The app now uses TenantManager which owns all per-tenant state.
We reset the default tenant's rate limiter before each test by
re-registering the default tenant — giving every test a fresh quota bucket.

Auth is disabled for tests via a FastAPI dependency override (not an
external AUTH_DISABLED env var) so `pytest tests/ -v` passes out of the
box for every contributor, regardless of their shell environment.
"""

import pytest
from fastapi.testclient import TestClient

import main as app_module
from custos.rate_limiter import QuotaConfig
from custos.tenant import TenantConfig

DEFAULT_QUOTA = QuotaConfig(
    requests_per_minute=60,
    requests_per_hour=1000,
    tokens_per_minute=100_000,
)


@pytest.fixture(autouse=True)
def _disable_auth_for_tests():
    """
    Override the optional_auth dependency for the whole test session so
    tests never depend on the AUTH_DISABLED environment variable being
    set externally. This makes `pytest tests/ -v` self-contained.
    """
    app_module.app.dependency_overrides[app_module.optional_auth] = lambda: None
    yield
    app_module.app.dependency_overrides.pop(app_module.optional_auth, None)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Re-register the default tenant before every test so each test
    starts with a full, clean quota bucket.
    """
    app_module.tenant_manager.register(
        "default",
        TenantConfig(tenant_id="default", quota=DEFAULT_QUOTA),
    )
    yield


@pytest.fixture
def client(reset_rate_limiter):
    """TestClient with a fresh default-tenant rate limiter and auth disabled."""
    from main import app
    return TestClient(app)
