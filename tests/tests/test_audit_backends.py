"""
Tests for v1.0 audit backends:
InMemoryBackend, SQLiteBackend, and AuditChain backend_type property.
PostgreSQL backend tested via mock to avoid requiring a live DB in CI.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import pytest
from custos.audit import (
    AuditChain,
    AuditRecord,
    InMemoryBackend,
    SQLiteBackend,
    PostgreSQLBackend,
)


class TestInMemoryBackend:
    def test_save_does_not_raise(self):
        backend = InMemoryBackend()
        record = AuditRecord(
            timestamp=1.0, client_id="c1", action="allow",
            triggered_rule=None, reason="ok", content_hash="abc",
            record_hash="def", previous_hash="000",
        )
        backend.save(record)  # should not raise

    def test_load_all_returns_empty(self):
        backend = InMemoryBackend()
        assert backend.load_all() == []


class TestSQLiteBackend:
    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        backend = SQLiteBackend(db_path)
        record = AuditRecord(
            timestamp=1.0, client_id="c1", action="allow",
            triggered_rule=None, reason="ok", content_hash="abc",
            record_hash="def", previous_hash="000",
        )
        backend.save(record)
        loaded = backend.load_all()
        assert len(loaded) == 1
        assert loaded[0].client_id == "c1"
        assert loaded[0].action == "allow"

    def test_multiple_records_ordered(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        backend = SQLiteBackend(db_path)
        for i in range(3):
            backend.save(AuditRecord(
                timestamp=float(i), client_id=f"c{i}", action="allow",
                triggered_rule=None, reason="ok", content_hash=f"hash{i}",
                record_hash=f"rec{i}", previous_hash=f"prev{i}",
            ))
        loaded = backend.load_all()
        assert len(loaded) == 3
        assert loaded[0].client_id == "c0"
        assert loaded[2].client_id == "c2"


class TestAuditChainBackends:
    def test_default_backend_is_in_memory(self):
        chain = AuditChain()
        assert chain.backend_type == "InMemoryBackend"

    def test_sqlite_backend_selected_by_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        chain = AuditChain(db_path=db_path)
        assert chain.backend_type == "SQLiteBackend"

    def test_sqlite_persists_across_instances(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        chain1 = AuditChain(db_path=db_path)
        chain1.record("c1", "allow", "ok", "content")

        chain2 = AuditChain(db_path=db_path)
        assert chain2.length == 1
        assert chain2.get_records()[0]["client_id"] == "c1"

    def test_chain_verify_after_reload(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        chain1 = AuditChain(db_path=db_path)
        chain1.record("c1", "allow", "ok", "first")
        chain1.record("c1", "deny", "pii", "second")

        chain2 = AuditChain(db_path=db_path)
        valid, reason = chain2.verify()
        assert valid is True

    def test_new_records_extend_reloaded_chain(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        chain1 = AuditChain(db_path=db_path)
        chain1.record("c1", "allow", "ok", "before")

        chain2 = AuditChain(db_path=db_path)
        chain2.record("c1", "allow", "ok", "after")
        assert chain2.length == 2
        valid, _ = chain2.verify()
        assert valid is True

    def test_postgresql_backend_raises_without_psycopg2(self):
        """PostgreSQL backend should raise RuntimeError if psycopg2 not installed."""
        import unittest.mock as mock
        with mock.patch.dict("sys.modules", {"psycopg2": None}):
            with pytest.raises((RuntimeError, ImportError)):
                PostgreSQLBackend("postgresql://localhost/test")


class TestVersionHeader:
    def test_version_header_present(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        resp = client.get("/health")
        assert "X-CUSTOS-Version" in resp.headers
        assert resp.headers["X-CUSTOS-Version"] == "1.0.0"

    def test_info_endpoint(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        resp = client.get("/v1/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1.0.0"
        assert "audit_backend" in data
        assert "tenant_count" in data
