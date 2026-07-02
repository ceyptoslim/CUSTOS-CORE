"""
Integration tests proving policy persistence is actually wired end-to-end
(issue #20). tests/test_policy_store.py only unit-tests PolicyStore in
isolation -- these tests prove TenantManager and the API actually use it,
so custom tenant policy rules survive a process restart.
"""

import tempfile

import pytest
from fastapi.testclient import TestClient

from custos.policy_engine import PolicyAction, PolicyRule
from custos.policy_store import PolicyStore
from custos.tenant import TenantConfig, TenantManager


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return f.name


class TestTenantManagerPersistsPolicyRules:
    def test_custom_rule_survives_new_tenant_manager_instance(self, db_path):
        """Simulates a pod restart: a brand new TenantManager sharing the
        same PolicyStore backend must recover the tenant AND its rule."""
        store1 = PolicyStore(db_path=db_path)
        mgr1 = TenantManager(policy_store=store1)
        mgr1.register("acme", TenantConfig(tenant_id="acme"))
        mgr1.add_policy_rule(
            "acme",
            PolicyRule("block_internal_codeword", r"(?i)project-zeta",
                       PolicyAction.DENY, "Internal codeword leak"),
        )

        # New process, new TenantManager, same durable store.
        store2 = PolicyStore(db_path=db_path)
        mgr2 = TenantManager(policy_store=store2)

        assert "acme" in mgr2.list_tenants()
        rules = mgr2.list_policy_rules("acme")
        assert len(rules) == 1
        assert rules[0].name == "block_internal_codeword"

        ctx = mgr2.get("acme")
        result = ctx.policy_engine.evaluate("mentioning project-zeta here")
        assert result.allowed is False
        assert result.triggered_rule == "block_internal_codeword"

    def test_default_tenant_custom_rules_survive_restart(self, db_path):
        store1 = PolicyStore(db_path=db_path)
        mgr1 = TenantManager(policy_store=store1)
        mgr1.add_policy_rule(
            "default",
            PolicyRule("block_foo", r"foo", PolicyAction.DENY, "no foo"),
        )

        store2 = PolicyStore(db_path=db_path)
        mgr2 = TenantManager(policy_store=store2)
        rules = mgr2.list_policy_rules("default")
        assert any(r.name == "block_foo" for r in rules)

    def test_in_memory_backend_does_not_persist(self):
        """Sanity check: without a durable backend, behavior is unchanged."""
        mgr1 = TenantManager(policy_store=PolicyStore())
        mgr1.register("temp", TenantConfig(tenant_id="temp"))
        mgr1.add_policy_rule(
            "temp", PolicyRule("r1", r"x", PolicyAction.DENY, "x")
        )

        mgr2 = TenantManager(policy_store=PolicyStore())
        assert "temp" not in mgr2.list_tenants()

    def test_unregister_deletes_persisted_rules(self, db_path):
        store = PolicyStore(db_path=db_path)
        mgr = TenantManager(policy_store=store)
        mgr.register("gone", TenantConfig(tenant_id="gone"))
        mgr.add_policy_rule(
            "gone", PolicyRule("r1", r"x", PolicyAction.DENY, "x")
        )
        assert mgr.unregister("gone") is True
        assert store.load("gone") == []


class TestPolicyRuleEndpoints:
    def test_add_rule_returns_200(self, client):
        resp = client.post("/v1/tenants/default/policy", json={
            "name": "block_test_marker",
            "pattern": "TESTMARKER123",
            "action": "deny",
            "reason": "test rule",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "default"
        assert data["rule"]["name"] == "block_test_marker"
        assert data["total_custom_rules"] >= 1

    def test_added_rule_is_enforced_immediately(self, client):
        client.post("/v1/tenants/default/policy", json={
            "name": "block_test_marker_2",
            "pattern": "SUPERSECRETMARKER",
            "action": "deny",
            "reason": "test rule",
        })
        resp = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "here is SUPERSECRETMARKER in the text",
        })
        assert resp.status_code == 200
        assert resp.json()["allowed"] is False
        assert resp.json()["triggered_rule"] == "block_test_marker_2"

    def test_invalid_action_returns_422(self, client):
        resp = client.post("/v1/tenants/default/policy", json={
            "name": "bad_rule",
            "pattern": "x",
            "action": "not_a_real_action",
            "reason": "x",
        })
        assert resp.status_code == 422

    def test_list_rules_returns_200(self, client):
        client.post("/v1/tenants/default/policy", json={
            "name": "list_test_rule",
            "pattern": "x",
            "action": "audit",
            "reason": "x",
        })
        resp = client.get("/v1/tenants/default/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "default"
        assert any(r["name"] == "list_test_rule" for r in data["rules"])

    def test_list_rules_for_unknown_tenant_falls_back_to_default(self, client):
        resp = client.get("/v1/tenants/ghost_tenant/policy")
        assert resp.status_code == 200
