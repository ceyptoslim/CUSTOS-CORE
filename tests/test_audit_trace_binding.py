"""Trace binding in the audit-chain preimage (EABC P7 remediation).

Property under test: the correlation identifier must be covered by the same
integrity evidence as the record it correlates (EABC docs/002, "Intrinsically
Bound"). Before this change `trace_id` was stored beside the record but sat
outside the `record_hash` preimage, so request-level correlation depended on an
unprotected field.

Backward compatibility is a hard requirement: records emitted under the legacy
preimage (binding_version 0) must verify byte-identically, forever.
"""
import hashlib
import json
import time

import pytest

from custos.audit import (
    RECORD_BINDING_CURRENT,
    AuditChain,
    AuditRecord,
    SQLiteBackend,
)


def _legacy_hash(record: AuditRecord, previous_hash: str) -> str:
    """The pre-change preimage, reproduced here as the compatibility oracle."""
    fields = {
        "timestamp": record.timestamp,
        "client_id": record.client_id,
        "action": record.action,
        "triggered_rule": record.triggered_rule,
        "reason": record.reason,
        "content_hash": record.content_hash,
        "previous_hash": previous_hash,
    }
    if record.policy_digest:
        fields["policy_digest"] = record.policy_digest
    if record.tenant_id:
        fields["tenant_id"] = record.tenant_id
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode("utf-8")).hexdigest()


def test_new_records_bind_trace_id():
    chain = AuditChain(_backend=None)
    rec = chain.record(
        client_id="tenant-a",
        action="tool.invoke",
        reason="allow",
        content="payload",
        trace_id="trace-abc",
    )
    assert rec.binding_version == RECORD_BINDING_CURRENT
    assert rec.binding_version >= 1
    assert chain.verify() == (True, "OK")


def test_mutating_trace_id_breaks_verification():
    chain = AuditChain()
    chain.record("tenant-a", "tool.invoke", "allow", "payload", trace_id="trace-abc")
    chain._records[0].trace_id = "trace-evil"
    ok, msg = chain.verify()
    assert ok is False
    assert "hash invalid" in msg or "mismatch" in msg


def test_dropping_trace_id_breaks_verification():
    chain = AuditChain()
    chain.record("tenant-a", "tool.invoke", "allow", "payload", trace_id="trace-abc")
    chain._records[0].trace_id = None
    ok, _ = chain.verify()
    assert ok is False


def test_relabelling_binding_version_breaks_verification():
    """A record cannot be downgraded to the legacy preimage to drop trace_id."""
    chain = AuditChain()
    chain.record("tenant-a", "tool.invoke", "allow", "payload", trace_id="trace-abc")
    chain._records[0].binding_version = 0
    ok, _ = chain.verify()
    assert ok is False


def test_legacy_record_still_verifies():
    """Records hashed under the old preimage verify unchanged."""
    ts = time.time()
    legacy = AuditRecord(
        timestamp=ts,
        client_id="tenant-a",
        action="tool.invoke",
        triggered_rule="rule-1",
        reason="allow",
        content_hash=hashlib.sha256(b"payload").hexdigest(),
        trace_id="trace-legacy",
        policy_digest="a" * 64,
        previous_hash=AuditChain.GENESIS_HASH,
    )
    legacy.record_hash = _legacy_hash(legacy, AuditChain.GENESIS_HASH)
    assert legacy.binding_version == 0

    chain = AuditChain()
    chain._records.append(legacy)
    assert chain.verify() == (True, "OK")


def test_mixed_chain_verifies_legacy_then_bound():
    ts = time.time()
    legacy = AuditRecord(
        timestamp=ts,
        client_id="tenant-a",
        action="tool.invoke",
        triggered_rule=None,
        reason="allow",
        content_hash=hashlib.sha256(b"one").hexdigest(),
        trace_id="trace-old",
        previous_hash=AuditChain.GENESIS_HASH,
    )
    legacy.record_hash = _legacy_hash(legacy, AuditChain.GENESIS_HASH)

    chain = AuditChain()
    chain._records.append(legacy)
    chain.record("tenant-a", "tool.invoke", "allow", "two", trace_id="trace-new")
    assert chain.verify() == (True, "OK")


def test_sqlite_round_trip_preserves_citation_and_binding(tmp_path):
    """Persistence must not strip the fields the preimage depends on."""
    db = str(tmp_path / "audit.db")
    chain = AuditChain(db_path=db)
    chain.record(
        "tenant-a",
        "tool.invoke",
        "allow",
        "payload",
        trace_id="trace-abc",
        policy_digest="b" * 64,
        tenant_id="tenant-a",
    )
    assert chain.verify() == (True, "OK")

    reloaded = AuditChain(db_path=db)
    assert len(reloaded._records) == 1
    rec = reloaded._records[0]
    assert rec.trace_id == "trace-abc"
    assert rec.policy_digest == "b" * 64
    assert rec.tenant_id == "tenant-a"
    assert rec.binding_version == RECORD_BINDING_CURRENT
    assert reloaded.verify() == (True, "OK")


def test_sqlite_migrates_pre_existing_table(tmp_path):
    """A database created by an older release gains the columns in place."""
    import sqlite3

    db = str(tmp_path / "old.db")
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE audit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                client_id TEXT NOT NULL,
                action TEXT NOT NULL,
                triggered_rule TEXT,
                reason TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                trace_id TEXT
            )
        """)
        conn.commit()

    SQLiteBackend(db)  # triggers migration
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_records)")}
    assert {"policy_digest", "tenant_id", "binding_version"} <= cols
