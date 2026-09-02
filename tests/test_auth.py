"""
Tests for JWT authentication (custos/auth.py) — Issue #3

Strategy: use FastAPI dependency_overrides to toggle auth enforcement
per-test. No env var flipping, no module reload needed.
"""

import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import jwt as pyjwt
from fastapi.testclient import TestClient

import main as app_module
from custos.auth import _JWT_SECRET, _JWT_ALGORITHM, create_token, verify_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enforce_auth(credentials=None):
    """Dependency override that always runs real JWT verification."""
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from fastapi import Request
    # Re-use the real verify_token — just bypass the AUTH_DISABLED check
    return verify_token(credentials)


@pytest.fixture
def client_with_auth():
    """TestClient where auth IS enforced regardless of AUTH_DISABLED env var."""
    from main import app, optional_auth
    # Override the optional_auth dependency to always enforce
    app.dependency_overrides[optional_auth] = verify_token
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_auth():
    """TestClient where auth is disabled (normal CI mode)."""
    from main import app
    return TestClient(app)


@pytest.fixture
def valid_token():
    return create_token("default")


@pytest.fixture
def expired_token():
    payload = {
        "sub": "default",
        "iat": int(time.time()) - 7200,
        "exp": int(time.time()) - 3600,
    }
    return pyjwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Token creation tests (no HTTP needed)
# ---------------------------------------------------------------------------

class TestTokenCreation:
    def test_create_token_returns_string(self):
        token = create_token("test_client")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_correct_subject(self):
        token = create_token("my_client")
        payload = pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        assert payload["sub"] == "my_client"

    def test_token_has_expiry(self):
        token = create_token("test_client", expires_in=300)
        payload = pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        assert "exp" in payload
        assert payload["exp"] > time.time()


# ---------------------------------------------------------------------------
# Auth enforcement tests (dependency override enables auth)
# ---------------------------------------------------------------------------

class TestAuthEnforcement:
    def test_missing_token_returns_401(self, client_with_auth):
        r = client_with_auth.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "hello",
        })
        assert r.status_code == 401

    def test_invalid_token_returns_401(self, client_with_auth):
        r = client_with_auth.post(
            "/v1/evaluate",
            json={"client_id": "default", "content": "hello"},
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert r.status_code == 401

    def test_expired_token_returns_403(self, client_with_auth, expired_token):
        r = client_with_auth.post(
            "/v1/evaluate",
            json={"client_id": "default", "content": "hello"},
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert r.status_code == 403

    def test_valid_token_allows_request(self, client_with_auth, valid_token):
        r = client_with_auth.post(
            "/v1/evaluate",
            json={"client_id": "default", "content": "Summarize document"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert r.status_code == 200

    def test_valid_token_on_clean_content_returns_allow(self, client_with_auth, valid_token):
        r = client_with_auth.post(
            "/v1/evaluate",
            json={"client_id": "default", "content": "What is the weather?"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        data = r.json()
        assert data["allowed"] is True
        assert data["action"] == "allow"

    def test_cross_client_access_denied(self, client_with_auth):
        token = create_token("alice")
        r = client_with_auth.post(
            "/v1/evaluate",
            json={"client_id": "bob", "content": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
        assert "Client identity does not match request client_id" in r.json()["detail"]

    def test_same_client_access_allowed(self, client_with_auth):
        token = create_token("alice")
        r = client_with_auth.post(
            "/v1/evaluate",
            json={"client_id": "alice", "content": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    def test_production_disables_auth_bypass(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("AUTH_DISABLED", "1")
        import main as app_module
        # Remove the test auth override so real auth runs
        saved = app_module.app.dependency_overrides.pop(app_module.optional_auth, None)
        try:
            with TestClient(app_module.app, raise_server_exceptions=False) as client:
                r = client.post("/v1/evaluate", json={"client_id": "alice", "content": "hello"})
                assert r.status_code == 401
        finally:
            if saved is not None:
                app_module.app.dependency_overrides[app_module.optional_auth] = saved

    def test_health_endpoint_requires_no_auth(self, client_with_auth):
        assert client_with_auth.get("/health").status_code == 200

    def test_metrics_endpoint_requires_no_auth(self, client_with_auth):
        assert client_with_auth.get("/metrics").status_code == 200

    def test_ready_endpoint_requires_no_auth(self, client_with_auth):
        assert client_with_auth.get("/ready").status_code == 200
