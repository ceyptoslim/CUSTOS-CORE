"""
Tenant Authorization Forensic Tests (v1.3.1)

Tests the P0/P1 finding from the forensic audit:
  - get_or_default() silently falls back to "default" for unknown tenant IDs
  - Several tenant-sensitive endpoints use this fallback
  - Cross-tenant access is possible via caller-controlled tenant_id

Fix: get_strict() returns None for unknown tenants. Request-handling
endpoints now reject unknown tenant IDs with 403.

These tests verify the fix and prevent regression.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import os
os.environ["AUTH_DISABLED"] = "1"

from fastapi.testclient import TestClient
from custos.tenant import TenantManager
import pytest


class TestTenantGetStrict:
    """get_strict() must NOT fall back to default for unknown tenants."""

    def test_known_tenant_returns_context(self):
        """The default tenant is always available via get_strict."""
        tm = TenantManager()
        ctx = tm.get_strict("default")
        assert ctx is not None
        assert ctx.tenant_id == "default"

    def test_unknown_tenant_returns_none(self):
        """Unknown tenant IDs must return None, not fall back to default."""
        tm = TenantManager()
        ctx = tm.get_strict("nonexistent-tenant-12345")
        assert ctx is None

    def test_registered_tenant_returns_context(self):
        """A registered tenant is available via get_strict."""
        tm = TenantManager()
        tm.register("acme-corp", __import__("custos.tenant", fromlist=["TenantConfig"]).TenantConfig(
            tenant_id="acme-corp"
        ))
        ctx = tm.get_strict("acme-corp")
        assert ctx is not None
        assert ctx.tenant_id == "acme-corp"

    def test_unregistered_tenant_does_not_get_default_context(self):
        """Critical: unknown tenant must not get the default tenant's policy engine."""
        tm = TenantManager()
        default_ctx = tm.get_strict("default")
        unknown_ctx = tm.get_strict("evil-tenant")
        assert unknown_ctx is None
        assert default_ctx is not None
        # The unknown tenant must not share the default's audit chain
        # (would be a cross-tenant data leak)

    def test_get_or_default_still_works_for_policy_management(self):
        """get_or_default is kept for internal policy management, not request paths."""
        tm = TenantManager()
        ctx = tm.get_or_default("some-new-tenant")
        assert ctx is not None
        assert ctx.tenant_id == "default"  # Falls back for management operations


class TestEndpointTenantRejection:
    """All request-handling endpoints must reject unknown tenant IDs with 403."""

    def setup_method(self):
        from main import app
        self.client = TestClient(app)

    def test_evaluate_rejects_unknown_tenant(self):
        """POST /v1/evaluate with unknown tenant_id → 403."""
        resp = self.client.post("/v1/evaluate", json={
            "content": "hello world",
            "client_id": "test",
            "tenant_id": "evil-tenant-xyz"
        })
        assert resp.status_code == 403
        assert "Unknown tenant" in resp.json()["detail"]

    def test_execute_not_available_in_public(self):
        """POST /v1/execute is not available in the public CUSTOS-CORE build.
        
        The /v1/execute endpoint is an enterprise feature assembled by the
        custos-enterprise package. In the public-only deployment, the endpoint
        is absent (404), not stubbed. When the enterprise router is installed,
        the endpoint is available and this test is skipped.
        """
        import importlib
        try:
            importlib.import_module("custos.enterprise_router")
            pytest.skip("Enterprise router installed — /v1/execute is available")
        except ImportError:
            pass
        resp = self.client.post("/v1/execute", json={
            "content": "hello world",
            "client_id": "test",
            "tenant_id": "evil-tenant-xyz",
            "target_url": "https://httpbin.org/get"
        })
        assert resp.status_code == 404

    def test_audit_records_rejects_unknown_tenant(self):
        """GET /v1/audit/records with unknown tenant_id → 403."""
        resp = self.client.get("/v1/audit?tenant_id=evil-tenant-xyz")
        assert resp.status_code == 403
        assert "Unknown tenant" in resp.json()["detail"]

    def test_audit_verify_rejects_unknown_tenant(self):
        """GET /v1/audit/verify with unknown tenant_id → 403."""
        resp = self.client.get("/v1/audit/verify?tenant_id=evil-tenant-xyz")
        assert resp.status_code == 403
        assert "Unknown tenant" in resp.json()["detail"]

    def test_snapshot_rejects_unknown_tenant(self):
        """GET /v1/audit/snapshot with unknown tenant_id → 403."""
        resp = self.client.get("/v1/audit/snapshot?tenant_id=evil-tenant-xyz")
        assert resp.status_code == 403
        assert "Unknown tenant" in resp.json()["detail"]

    def test_replay_rejects_unknown_tenant(self):
        """POST /v1/replay with unknown tenant_id → 403."""
        resp = self.client.post("/v1/replay", json={
            "record_hash": "a" * 64,
            "original_content": "test content",
            "tenant_id": "evil-tenant-xyz"
        })
        assert resp.status_code == 403
        assert "Unknown tenant" in resp.json()["detail"]

    def test_default_tenant_still_works(self):
        """The default tenant must still work on all endpoints."""
        resp = self.client.post("/v1/evaluate", json={
            "content": "hello world",
            "client_id": "test",
            "tenant_id": "default"
        })
        assert resp.status_code == 200
        assert resp.json()["allowed"] is True

    def test_no_tenant_defaults_to_default(self):
        """If tenant_id is omitted, the default tenant is used (not 403)."""
        resp = self.client.post("/v1/evaluate", json={
            "content": "hello world",
            "client_id": "test"
        })
        assert resp.status_code == 200

    def test_cross_tenant_isolation_audit(self):
        """Tenant A's audit records must not be accessible via tenant B's context."""
        # Post to default tenant
        self.client.post("/v1/evaluate", json={
            "content": "default tenant content",
            "client_id": "client-a",
            "tenant_id": "default"
        })

        # Register a second tenant
        from custos.tenant import TenantManager, TenantConfig
        tenant_manager = TenantManager()
        # Use the global instance
        from main import tenant_manager as global_tm
        global_tm.register("tenant-b", TenantConfig(tenant_id="tenant-b"))

        # Try to access default's audit via the unknown tenant path
        resp = self.client.get("/v1/audit?tenant_id=tenant-b")
        assert resp.status_code == 200
        data = resp.json()
        # Tenant B should have NO records (it's a different tenant)
        records = data if isinstance(data, list) else data.get("records", [])
        assert len(records) == 0, "Tenant B should not see Tenant A's audit records"


class TestOPAStrictResponseTyping:
    """OPA response must use strict Boolean validation, not truthiness."""

    def test_string_truthy_rejected(self):
        """A non-empty string 'allow' must not authorize (bool() would accept it)."""
        from custos.opa_engine import OPAPolicyEngine
        from unittest.mock import patch, MagicMock
        import httpx

        engine = OPAPolicyEngine(opa_url="http://localhost:9999")

        # Mock OPA returning allow as a string (malformed)
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"allow": "true"}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = engine.evaluate("hello world")

        # Must be denied — string "true" is not boolean True
        assert result.allowed is False, "String 'true' must not authorize — strict Boolean check required"

    def test_integer_one_rejected(self):
        """Integer 1 must not authorize (bool(1) is True but 1 is not True)."""
        from custos.opa_engine import OPAPolicyEngine
        from unittest.mock import patch, MagicMock
        import httpx

        engine = OPAPolicyEngine(opa_url="http://localhost:9999")

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"allow": 1}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = engine.evaluate("hello world")

        assert result.allowed is False, "Integer 1 must not authorize — strict Boolean check required"

    def test_boolean_true_accepted(self):
        """Literal boolean True must authorize."""
        from custos.opa_engine import OPAPolicyEngine
        from unittest.mock import patch, MagicMock
        import httpx

        engine = OPAPolicyEngine(opa_url="http://localhost:9999")

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"allow": True}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = engine.evaluate("hello world")

        assert result.allowed is True, "Literal True must authorize"

    def test_empty_dict_rejected(self):
        """An empty result dict (no 'allow' field) must not authorize."""
        from custos.opa_engine import OPAPolicyEngine
        from unittest.mock import patch, MagicMock
        import httpx

        engine = OPAPolicyEngine(opa_url="http://localhost:9999")

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = engine.evaluate("hello world")

        assert result.allowed is False, "Empty result dict must not authorize"
