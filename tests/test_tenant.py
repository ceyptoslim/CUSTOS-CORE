"""
Tests for custos/tenant.py and /v1/tenants endpoints
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from custos.tenant import TenantConfig, TenantManager
from custos.rate_limiter import QuotaConfig
from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def manager():
    return TenantManager()


class TestTenantManager:
    def test_default_tenant_exists(self, manager):
        ctx = manager.get("default")
        assert ctx is not None
        assert ctx.tenant_id == "default"

    def test_register_new_tenant(self, manager):
        config = TenantConfig(
            tenant_id="acme",
            quota=QuotaConfig(requests_per_minute=10, requests_per_hour=100),
        )
        ctx = manager.register("acme", config)
        assert ctx.tenant_id == "acme"

    def test_get_registered_tenant(self, manager):
        config = TenantConfig(
            tenant_id="corp",
            quota=QuotaConfig(requests_per_minute=10, requests_per_hour=100),
        )
        manager.register("corp", config)
        ctx = manager.get("corp")
        assert ctx is not None
        assert ctx.tenant_id == "corp"

    def test_get_unknown_returns_none(self, manager):
        assert manager.get("ghost") is None

    def test_get_or_default_falls_back(self, manager):
        ctx = manager.get_or_default("unknown_tenant")
        assert ctx.tenant_id == "default"

    def test_tenants_are_isolated(self, manager):
        """Policy engine instances must be separate objects."""
        config_a = TenantConfig("a", QuotaConfig(10, 100))
        config_b = TenantConfig("b", QuotaConfig(10, 100))
        ctx_a = manager.register("a", config_a)
        ctx_b = manager.register("b", config_b)
        assert ctx_a.policy_engine is not ctx_b.policy_engine
        assert ctx_a.rate_limiter is not ctx_b.rate_limiter
        assert ctx_a.audit_chain is not ctx_b.audit_chain

    def test_rate_limiter_isolation(self, manager):
        """Exhausting tenant A quota must not affect tenant B."""
        config_a = TenantConfig("rl_a", QuotaConfig(
            requests_per_minute=1, requests_per_hour=100))
        config_b = TenantConfig("rl_b", QuotaConfig(
            requests_per_minute=10, requests_per_hour=100))
        ctx_a = manager.register("rl_a", config_a)
        ctx_b = manager.register("rl_b", config_b)

        # Exhaust tenant A
        ctx_a.rate_limiter.check_and_consume("rl_a")
        allowed_a, _ = ctx_a.rate_limiter.check_and_consume("rl_a")
        allowed_b, _ = ctx_b.rate_limiter.check_and_consume("rl_b")

        assert allowed_a is False
        assert allowed_b is True

    def test_audit_isolation(self, manager):
        """Tenant A audit records must not appear in tenant B."""
        config_a = TenantConfig("audit_a", QuotaConfig(10, 100))
        config_b = TenantConfig("audit_b", QuotaConfig(10, 100))
        ctx_a = manager.register("audit_a", config_a)
        ctx_b = manager.register("audit_b", config_b)

        ctx_a.audit_chain.record("u1", "allow", "ok", "content for A")
        records_b = ctx_b.audit_chain.get_records()
        assert len(records_b) == 0

    def test_unregister_removes_tenant(self, manager):
        config = TenantConfig("to_remove", QuotaConfig(10, 100))
        manager.register("to_remove", config)
        removed = manager.unregister("to_remove")
        assert removed is True
        assert manager.get("to_remove") is None

    def test_cannot_unregister_default(self, manager):
        removed = manager.unregister("default")
        assert removed is False
        assert manager.get("default") is not None

    def test_list_tenants_includes_default(self, manager):
        tenants = manager.list_tenants()
        assert "default" in tenants

    def test_count_increments_on_register(self, manager):
        initial = manager.count
        config = TenantConfig("counter_test", QuotaConfig(10, 100))
        manager.register("counter_test", config)
        assert manager.count == initial + 1


class TestTenantEndpoints:
    def test_list_tenants_returns_200(self, client):
        resp = client.get("/v1/tenants")
        assert resp.status_code == 200

    def test_list_includes_default(self, client):
        resp = client.get("/v1/tenants")
        assert "default" in resp.json()["tenants"]

    def test_register_tenant_returns_201(self, client):
        resp = client.post("/v1/tenants", json={
            "tenant_id": "test_corp",
            "requests_per_minute": 30,
            "requests_per_hour": 500,
            "tokens_per_minute": 50000,
        })
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "test_corp"

    def test_register_duplicate_returns_409(self, client):
        client.post("/v1/tenants", json={"tenant_id": "dup_tenant"})
        resp = client.post("/v1/tenants", json={"tenant_id": "dup_tenant"})
        assert resp.status_code == 409

    def test_register_default_returns_400(self, client):
        resp = client.post("/v1/tenants", json={"tenant_id": "default"})
        assert resp.status_code == 400

    def test_delete_tenant_returns_200(self, client):
        client.post("/v1/tenants", json={"tenant_id": "to_delete"})
        resp = client.delete("/v1/tenants/to_delete")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_default_returns_400(self, client):
        resp = client.delete("/v1/tenants/default")
        assert resp.status_code == 400

    def test_delete_unknown_returns_404(self, client):
        resp = client.delete("/v1/tenants/ghost_tenant_xyz")
        assert resp.status_code == 404

    def test_evaluate_with_tenant_id(self, client):
        client.post("/v1/tenants", json={"tenant_id": "eval_tenant"})
        resp = client.post("/v1/evaluate", json={
            "client_id": "user1",
            "content": "Hello from eval_tenant",
            "tenant_id": "eval_tenant",
        })
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == "eval_tenant"

    def test_audit_isolated_per_tenant(self, client):
        client.post("/v1/tenants", json={"tenant_id": "iso_a"})
        client.post("/v1/tenants", json={"tenant_id": "iso_b"})
        client.post("/v1/evaluate", json={
            "client_id": "u1", "content": "tenant A content",
            "tenant_id": "iso_a",
        })
        resp = client.get("/v1/audit?tenant_id=iso_b")
        records = resp.json()
        assert all(r["client_id"] != "u1" for r in records)
