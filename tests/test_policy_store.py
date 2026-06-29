"""
Tests for custos/policy_store.py — issue #20
Policy persistence across restarts.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import pytest
from custos.policy_store import (
    InMemoryPolicyBackend,
    PolicyStore,
    SQLitePolicyBackend,
)
from custos.policy_engine import PolicyAction, PolicyRule


@pytest.fixture
def default_rules():
    return [
        PolicyRule("block_ssn", r"\b\d{3}-\d{2}-\d{4}\b",
                   PolicyAction.DENY, "SSN detected"),
        PolicyRule("audit_password", r"(?i)\bpassword\b",
                   PolicyAction.AUDIT, "Password keyword"),
    ]


class TestInMemoryPolicyBackend:
    def test_save_and_load(self, default_rules):
        backend = InMemoryPolicyBackend()
        backend.save_rules("tenant_a", default_rules)
        loaded = backend.load_rules("tenant_a")
        assert len(loaded) == 2
        assert loaded[0].name == "block_ssn"

    def test_load_unknown_tenant_returns_empty(self):
        backend = InMemoryPolicyBackend()
        assert backend.load_rules("ghost") == []

    def test_save_replaces_existing(self, default_rules):
        backend = InMemoryPolicyBackend()
        backend.save_rules("t1", default_rules)
        new_rules = [PolicyRule("new_rule", r"test",
                                PolicyAction.DENY, "test")]
        backend.save_rules("t1", new_rules)
        loaded = backend.load_rules("t1")
        assert len(loaded) == 1
        assert loaded[0].name == "new_rule"

    def test_delete_tenant(self, default_rules):
        backend = InMemoryPolicyBackend()
        backend.save_rules("t1", default_rules)
        backend.delete_tenant("t1")
        assert backend.load_rules("t1") == []

    def test_list_tenants(self, default_rules):
        backend = InMemoryPolicyBackend()
        backend.save_rules("t1", default_rules)
        backend.save_rules("t2", default_rules)
        tenants = backend.list_tenants()
        assert "t1" in tenants
        assert "t2" in tenants

    def test_tenant_isolation(self, default_rules):
        backend = InMemoryPolicyBackend()
        backend.save_rules("t1", default_rules)
        assert backend.load_rules("t2") == []


class TestSQLitePolicyBackend:
    def test_save_and_load(self, default_rules):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        backend = SQLitePolicyBackend(db_path)
        backend.save_rules("tenant_a", default_rules)
        loaded = backend.load_rules("tenant_a")
        assert len(loaded) == 2
        assert loaded[0].name == "block_ssn"
        assert loaded[0].action == PolicyAction.DENY

    def test_persists_across_instances(self, default_rules):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        backend1 = SQLitePolicyBackend(db_path)
        backend1.save_rules("t1", default_rules)

        backend2 = SQLitePolicyBackend(db_path)
        loaded = backend2.load_rules("t1")
        assert len(loaded) == 2

    def test_save_replaces_existing(self, default_rules):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        backend = SQLitePolicyBackend(db_path)
        backend.save_rules("t1", default_rules)
        new_rules = [PolicyRule("new", r"x", PolicyAction.DENY, "x")]
        backend.save_rules("t1", new_rules)
        loaded = backend.load_rules("t1")
        assert len(loaded) == 1

    def test_delete_tenant(self, default_rules):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        backend = SQLitePolicyBackend(db_path)
        backend.save_rules("t1", default_rules)
        backend.delete_tenant("t1")
        assert backend.load_rules("t1") == []


class TestPolicyStore:
    def test_default_backend_is_in_memory(self):
        store = PolicyStore()
        assert store.backend_type == "InMemoryPolicyBackend"

    def test_sqlite_backend_selected_by_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        store = PolicyStore(db_path=db_path)
        assert store.backend_type == "SQLitePolicyBackend"

    def test_save_and_load(self, default_rules):
        store = PolicyStore()
        store.save("t1", default_rules)
        loaded = store.load("t1")
        assert len(loaded) == 2

    def test_load_empty_for_unknown_tenant(self):
        store = PolicyStore()
        assert store.load("nobody") == []

    def test_delete_removes_rules(self, default_rules):
        store = PolicyStore()
        store.save("t1", default_rules)
        store.delete("t1")
        assert store.load("t1") == []

    def test_list_tenants(self, default_rules):
        store = PolicyStore()
        store.save("t1", default_rules)
        store.save("t2", default_rules)
        tenants = store.list_tenants()
        assert "t1" in tenants
        assert "t2" in tenants

    def test_sqlite_persists_across_store_instances(self, default_rules):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        store1 = PolicyStore(db_path=db_path)
        store1.save("t1", default_rules)

        store2 = PolicyStore(db_path=db_path)
        loaded = store2.load("t1")
        assert len(loaded) == 2
        assert loaded[0].action == PolicyAction.DENY
      
