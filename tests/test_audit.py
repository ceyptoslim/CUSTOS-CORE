"""
Tests for SQLite audit persistence — Issue #4
"""

import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from custos.audit import AuditChain


@pytest.fixture
def chain():
    """In-memory chain (no db_path)."""
    return AuditChain()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_audit.db")


@pytest.fixture
def persisted_chain(db_path):
    return AuditChain(db_path=db_path)


class TestInMemoryAudit:
    def test_record_appends(self, chain):
        chain.record("client_a", "allow", "No violations", "hello world")
        assert chain.length == 1

    def test_record_returns_audit_record(self, chain):
        entry = chain.record("client_a", "deny", "SSN detected", "123-45-6789")
        assert entry.action == "deny"
        assert entry.client_id == "client_a"
        assert len(entry.record_hash) == 64

    def test_chain_verify_passes_on_valid_chain(self, chain):
        chain.record("c1", "allow", "ok", "content 1")
        chain.record("c1", "deny", "pii", "content 2")
        valid, msg = chain.verify()
        assert valid is True

    def test_chain_verify_detects_tampering(self, chain):
        chain.record("c1", "allow", "ok", "legit content")
        # Tamper with the first record's hash directly
        chain._records[0].record_hash = "0" * 64
        valid, msg = chain.verify()
        assert valid is False
        assert "tampering" in msg.lower() or "mismatch" in msg.lower()

    def test_genesis_hash_is_64_zeros(self, chain):
        assert chain.GENESIS_HASH == "0" * 64

    def test_first_record_previous_hash_is_genesis(self, chain):
        entry = chain.record("c1", "allow", "ok", "first")
        assert entry.previous_hash == AuditChain.GENESIS_HASH

    def test_second_record_links_to_first(self, chain):
        first = chain.record("c1", "allow", "ok", "first")
        second = chain.record("c1", "allow", "ok", "second")
        assert second.previous_hash == first.record_hash

    def test_content_is_hashed_not_stored(self, chain):
        raw = "My SSN is 123-45-6789"
        entry = chain.record("c1", "deny", "pii", raw)
        assert raw not in entry.content_hash
        assert len(entry.content_hash) == 64

    def test_get_records_filtered_by_client(self, chain):
        chain.record("alice", "allow", "ok", "a")
        chain.record("bob", "deny", "pii", "b")
        alice_records = chain.get_records(client_id="alice")
        assert len(alice_records) == 1
        assert alice_records[0]["client_id"] == "alice"


class TestSQLitePersistence:
    def test_records_persist_across_instances(self, db_path):
        # Write with first instance
        chain1 = AuditChain(db_path=db_path)
        chain1.record("c1", "allow", "ok", "persistent content")
        assert chain1.length == 1

        # Read with second instance (simulates restart)
        chain2 = AuditChain(db_path=db_path)
        assert chain2.length == 1
        records = chain2.get_records()
        assert records[0]["client_id"] == "c1"
        assert records[0]["action"] == "allow"

    def test_chain_integrity_survives_reload(self, db_path):
        chain1 = AuditChain(db_path=db_path)
        chain1.record("c1", "allow", "ok", "first")
        chain1.record("c1", "deny", "pii", "second")

        chain2 = AuditChain(db_path=db_path)
        valid, msg = chain2.verify()
        assert valid is True, f"Chain failed verification after reload: {msg}"

    def test_new_records_extend_reloaded_chain(self, db_path):
        chain1 = AuditChain(db_path=db_path)
        chain1.record("c1", "allow", "ok", "before restart")

        chain2 = AuditChain(db_path=db_path)
        chain2.record("c1", "allow", "ok", "after restart")
        assert chain2.length == 2
        valid, msg = chain2.verify()
        assert valid is True

    def test_in_memory_chain_has_no_db(self, chain):
        """Confirm default chain does not touch the filesystem."""
        assert chain._conn is None
        assert chain._db_path is None
