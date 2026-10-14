"""
Tests for custos/policy_store.py — issue #20
Policy persistence across restarts.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile

import pytest

from custos.policy_engine import PolicyAction, PolicyRule
from custos.policy_store import (
    InMemoryPolicyBackend,
    PolicyStore,
    SQLitePolicyBackend,
)


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
      


# ---------------------------------------------------------------------------
# PostgreSQLPolicyBackend (mock-based; no live DB required in CI).
# Closes the Sept 6 audit gap: zero test coverage on the PostgreSQL
# policy backend (InMemory and SQLite were covered; PostgreSQL was not).
# ---------------------------------------------------------------------------

import types
import unittest.mock as _mock


class _FakePgCursor:
    """Interprets the five SQL statements PostgreSQLPolicyBackend issues."""

    def __init__(self, db):
        self._db = db
        self._result = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        s = " ".join(sql.split()).upper()
        self._db.statements.append(s)
        if s.startswith("CREATE TABLE"):
            self._db.schema_created = True
        elif s.startswith("INSERT INTO POLICY_RULES"):
            tenant, name, pattern, action, reason = params
            self._db.rows.append({
                "tenant": tenant, "name": name, "pattern": pattern,
                "action": action, "reason": reason,
            })
        elif s.startswith("DELETE FROM POLICY_RULES WHERE TENANT_ID = %S"):
            self._db.rows = [r for r in self._db.rows if r["tenant"] != params[0]]
        elif s.startswith("SELECT NAME, PATTERN, ACTION, REASON"):
            # insertion order == id ASC
            self._result = [
                (r["name"], r["pattern"], r["action"], r["reason"])
                for r in self._db.rows if r["tenant"] == params[0]
            ]
        elif s.startswith("SELECT DISTINCT TENANT_ID"):
            seen = []
            for r in self._db.rows:
                if r["tenant"] not in seen:
                    seen.append(r["tenant"])
            self._result = [(t,) for t in seen]
        else:
            raise AssertionError("unexpected SQL issued: " + s)

    def fetchall(self):
        return self._result


class _FakePgConn:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _FakePgCursor(self._db)

    def commit(self):
        self._db.commits += 1


class _FakePgDatabase:
    """Stateful fake psycopg2 module: records statements, rows, commits."""

    def __init__(self):
        self.rows = []
        self.statements = []
        self.commits = 0
        self.connect_urls = []
        self.schema_created = False
        self.module = types.ModuleType("psycopg2")
        self.module.connect = self._connect

    def _connect(self, url):
        self.connect_urls.append(url)
        return _FakePgConn(self)

    def patch(self):
        return _mock.patch.dict("sys.modules", {"psycopg2": self.module})


class TestPostgreSQLPolicyBackend:
    DB_URL = "postgresql://custos:test@localhost:5432/custos"

    def _backend(self, db=None):
        from custos.policy_store import PostgreSQLPolicyBackend
        db = db if db is not None else _FakePgDatabase()
        with db.patch():
            backend = PostgreSQLPolicyBackend(self.DB_URL)
        return db, backend

    def test_init_raises_without_psycopg2(self):
        from custos.policy_store import PostgreSQLPolicyBackend
        with _mock.patch.dict("sys.modules", {"psycopg2": None}):
            with pytest.raises(RuntimeError, match="psycopg2"):
                PostgreSQLPolicyBackend(self.DB_URL)

    def test_schema_created_on_init(self):
        db, _ = self._backend()
        assert db.schema_created is True, "backend must issue CREATE TABLE IF NOT EXISTS on init"
        assert db.connect_urls == [self.DB_URL], "connection must use the provided database URL"

    def test_save_and_load_roundtrip(self, default_rules):
        _, backend = self._backend()
        backend.save_rules("t1", default_rules)
        loaded = backend.load_rules("t1")
        assert [r.name for r in loaded] == ["block_ssn", "audit_password"]
        assert loaded[0].action is PolicyAction.DENY
        assert loaded[1].action is PolicyAction.AUDIT
        assert loaded[0].pattern == r"\b\d{3}-\d{2}-\d{4}\b"
        assert loaded[0].reason == "SSN detected"

    def test_load_unknown_tenant_returns_empty(self):
        _, backend = self._backend()
        assert backend.load_rules("nobody") == []

    def test_save_replaces_existing(self, default_rules):
        _, backend = self._backend()
        backend.save_rules("t1", default_rules)
        backend.save_rules("t1", [default_rules[0]])
        loaded = backend.load_rules("t1")
        assert len(loaded) == 1
        assert loaded[0].name == "block_ssn"

    def test_delete_tenant(self, default_rules):
        _, backend = self._backend()
        backend.save_rules("t1", default_rules)
        backend.save_rules("t2", default_rules)
        backend.delete_tenant("t1")
        assert backend.load_rules("t1") == []
        assert len(backend.load_rules("t2")) == 2

    def test_tenant_isolation(self, default_rules):
        _, backend = self._backend()
        backend.save_rules("t1", default_rules[:1])
        backend.save_rules("t2", default_rules[1:])
        assert [r.name for r in backend.load_rules("t1")] == ["block_ssn"]
        assert [r.name for r in backend.load_rules("t2")] == ["audit_password"]

    def test_list_tenants_distinct_ordered(self, default_rules):
        _, backend = self._backend()
        backend.save_rules("t1", default_rules)
        backend.save_rules("t1", default_rules)  # same tenant twice
        backend.save_rules("t2", default_rules)
        assert backend.list_tenants() == ["t1", "t2"]

    def test_save_issues_delete_before_insert(self, default_rules):
        db, backend = self._backend()
        db.statements.clear()
        backend.save_rules("t1", default_rules)
        stmts = db.statements
        assert "DELETE FROM POLICY_RULES WHERE TENANT_ID = %S" in stmts
        first_insert = next(i for i, s in enumerate(stmts) if s.startswith("INSERT INTO POLICY_RULES"))
        assert stmts.index("DELETE FROM POLICY_RULES WHERE TENANT_ID = %S") < first_insert, \
            "save_rules must DELETE the tenant's rows before INSERTing (replace semantics)"

    def test_save_commits(self, default_rules):
        db, backend = self._backend()
        db.commits = 0
        backend.save_rules("t1", default_rules)
        assert db.commits == 1, "save_rules must commit its transaction"

    def test_connection_url_passed_on_every_operation(self, default_rules):
        db, backend = self._backend()
        backend.save_rules("t1", default_rules)
        backend.load_rules("t1")
        backend.list_tenants()
        assert db.connect_urls == [self.DB_URL] * 4, \
            "every operation must connect with the configured URL (init + save + load + list)"

    def test_factory_selects_postgres_by_database_url(self, default_rules, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        db = _FakePgDatabase()
        with db.patch():
            store = PolicyStore(database_url=self.DB_URL)
        assert store.backend_type == "PostgreSQLPolicyBackend"
        store.save("t1", default_rules)
        assert len(store.load("t1")) == 2
