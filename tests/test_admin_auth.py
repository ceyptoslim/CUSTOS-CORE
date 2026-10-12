"""
Regression tests: administrative endpoints REQUIRE auth when enabled.

Fixes the missing-auth finding (Oct 2026 audit, live-verified): /v1/audit,
/v1/audit/verify, /v1/audit/snapshot, /v1/replay, /v1/policy/diff and all
/v1/tenants endpoints previously had NO auth dependency — anyone could read
any tenant's audit log or register/delete tenants.
"""

import pytest
from fastapi.testclient import TestClient

import main as app_module
from custos.auth import create_token


@pytest.fixture
def client_with_auth(monkeypatch):
    """Client with dependency overrides CLEARED and auth force-enabled."""
    saved = dict(app_module.app.dependency_overrides)
    app_module.app.dependency_overrides.clear()
    monkeypatch.setattr(app_module, "auth_enabled", lambda: True)
    yield TestClient(app_module.app)
    app_module.app.dependency_overrides.clear()
    app_module.app.dependency_overrides.update(saved)


ADMIN_ENDPOINTS = [
    "/v1/audit",
    "/v1/audit/verify",
    "/v1/audit/snapshot",
    "/v1/tenants",
]


class TestAdminEndpointsRequireAuth:
    def test_audit_endpoints_reject_missing_token(self, client_with_auth):
        for ep in ADMIN_ENDPOINTS:
            r = client_with_auth.get(ep)
            assert r.status_code == 401, f"{ep} must require auth, got {r.status_code}"

    def test_replay_rejects_missing_token(self, client_with_auth):
        r = client_with_auth.post("/v1/replay", json={"record_hash": "x" * 64})
        assert r.status_code == 401

    def test_tenant_register_rejects_missing_token(self, client_with_auth):
        r = client_with_auth.post(
            "/v1/tenants", json={"tenant_id": "evil", "quota": {}}
        )
        assert r.status_code == 401

    def test_tenant_delete_rejects_missing_token(self, client_with_auth):
        r = client_with_auth.delete("/v1/tenants/some-tenant")
        assert r.status_code == 401

    def test_valid_token_allows_audit_read(self, client_with_auth):
        token = create_token("admin")
        r = client_with_auth.get(
            "/v1/audit", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200

    def test_invalid_token_rejected(self, client_with_auth):
        r = client_with_auth.get(
            "/v1/audit", headers={"Authorization": "Bearer not.a.token"}
        )
        assert r.status_code == 401
