"""
Tests for JWT authentication (custos/auth.py) — Issue #3
"""

import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import jwt as pyjwt
from fastapi.testclient import TestClient

from custos.auth import _JWT_SECRET, _JWT_ALGORITHM, create_token


@pytest.fixture
def client():
    os.environ["AUTH_DISABLED"] = "0"
    from main import app
    c = TestClient(app, raise_server_exceptions=True)
    yield c
    os.environ["AUTH_DISABLED"] = "1"  # restore default for other tests


@pytest.fixture
def valid_token():
    return create_token("default")


@pytest.fixture
def expired_token():
    payload = {
        "sub": "default",
        "iat": int(time.time()) - 7200,
        "exp": int(time.time()) - 3600,  # already expired
    }
    return pyjwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


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


class TestAuthEnforcement:
    def test_missing_token_returns_401(self, client):
        r = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "hello",
        })
        assert r.status_code == 401

    def test_invalid_token_returns_401(self, client):
        r = client.post(
            "/v1/evaluate",
            json={"client_id": "default", "content": "hello"},
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert r.status_code == 401

    def test_expired_token_returns_403(self, client, expired_token):
        r = client.post(
            "/v1/evaluate",
            json={"client_id": "default", "content": "hello"},
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert r.status_code == 403

    def test_valid_token_allows_request(self, client, valid_token):
        r = client.post(
            "/v1/evaluate",
            json={"client_id": "default", "content": "Summarize document"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert r.status_code == 200

    def test_valid_token_on_clean_content_returns_allow(self, client, valid_token):
        r = client.post(
            "/v1/evaluate",
            json={"client_id": "default", "content": "What is the weather?"},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        data = r.json()
        assert data["allowed"] is True
        assert data["action"] == "allow"

    def test_health_endpoint_requires_no_auth(self, client):
        """Health and metrics must remain unauthenticated for load balancer probes."""
        assert client.get("/health").status_code == 200

    def test_metrics_endpoint_requires_no_auth(self, client):
        assert client.get("/metrics").status_code == 200

    def test_ready_endpoint_requires_no_auth(self, client):
        assert client.get("/ready").status_code == 200
