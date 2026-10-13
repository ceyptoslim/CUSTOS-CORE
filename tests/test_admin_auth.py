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


class TestAdminRouterProtection:
    """Future-proofing: every administrative path must be mounted on
    admin_router (which carries require_auth at the router level). This
    fails loudly if someone mounts an admin route on bare @app or on any
    router without the auth dependency."""

    ADMIN_PATHS = {
        "/v1/audit",
        "/v1/audit/verify",
        "/v1/audit/snapshot",
        "/v1/audit/snapshot/verify",
        "/v1/replay",
        "/v1/policy/diff",
        "/v1/tenants",
        "/v1/tenants/{tenant_id}",
        "/v1/tenants/{tenant_id}/policy",
    }

    def test_admin_routes_mounted_only_on_protected_router(self):
        from fastapi.routing import APIRoute

        # no admin path may exist as a bare top-level APIRoute
        for route in app_module.app.routes:
            if isinstance(route, APIRoute) and route.path in self.ADMIN_PATHS:
                raise AssertionError(
                    f"{route.path} is mounted on bare @app — mount it on "
                    "admin_router so it inherits require_auth."
                )

        # the admin router must carry the auth dependency and cover all paths
        included = [
            r for r in app_module.app.routes
            if type(r).__name__ == "_IncludedRouter"
            and getattr(r, "original_router", None) is app_module.admin_router
        ]
        assert included, "admin_router was never included into the app"

        deps = [d.dependency for d in app_module.admin_router.dependencies]
        assert app_module.require_auth in deps, (
            "admin_router lost its require_auth dependency"
        )

        router_paths = {
            getattr(r, "path", None) for r in app_module.admin_router.routes
        }
        missing = self.ADMIN_PATHS - router_paths
        assert not missing, f"admin paths missing from admin_router: {missing}"
