"""
Single-writer is a property of the store, not a rule the operator remembers.

The failure these tests cover, observed before the constraint existed: two
processes each construct a chain against the same SQLite store before either
appends. Both read the same head. Both then append a record naming that head as
its predecessor. The store ends up holding two records that claim the same
parent, which is a fork. Each writer's own verification returns OK, because each
walks only the list it holds in memory. Only a later reader sees the damage, and
what it sees is indistinguishable from an edit.

With the unique index, the second append is refused at the store, while the
process that would have caused the fork is still running and can still be told
why. These tests pin that behaviour, and they pin the part that matters most:
the refusal leaves a store that still verifies.
"""
import sqlite3

import pytest

from custos.audit import AuditChain


def _fork_error():
    """Resolve the error class at call time.

    Another module in this suite reloads custos.audit, which rebinds the class
    object. Importing at module scope would compare against a stale one and the
    guard would silently stop asserting anything.
    """
    from custos.audit import ChainForkError

    return ChainForkError


def _seed(db_path, n=1):
    chain = AuditChain(db_path=db_path)
    for i in range(n):
        chain.record(client_id="seed", action=f"seed_{i}", reason="ok", content=f"c{i}")
    return chain


class TestForkIsRefusedAtTheStore:
    def test_two_writers_loaded_before_either_appends(self, tmp_path):
        db = str(tmp_path / "audit.sqlite")
        _seed(db)

        # Both processes start against the same store before any append.
        w1 = AuditChain(db_path=db)
        w2 = AuditChain(db_path=db)
        assert w1._records[-1].record_hash == w2._records[-1].record_hash

        w1.record(client_id="a", action="from_A", reason="ok", content="a")
        with pytest.raises(_fork_error()):
            w2.record(client_id="b", action="from_B", reason="ok", content="b")

    def test_refusal_leaves_a_verifiable_store(self, tmp_path):
        db = str(tmp_path / "audit.sqlite")
        _seed(db)
        w1 = AuditChain(db_path=db)
        w2 = AuditChain(db_path=db)
        w1.record(client_id="a", action="from_A", reason="ok", content="a")
        with pytest.raises(_fork_error()):
            w2.record(client_id="b", action="from_B", reason="ok", content="b")

        fresh = AuditChain(db_path=db)
        assert fresh.verify() == (True, "OK")
        assert len(fresh._records) == 2

    def test_a_reloaded_writer_can_append(self, tmp_path):
        db = str(tmp_path / "audit.sqlite")
        _seed(db)
        w1 = AuditChain(db_path=db)
        w2 = AuditChain(db_path=db)
        w1.record(client_id="a", action="from_A", reason="ok", content="a")
        with pytest.raises(_fork_error()):
            w2.record(client_id="b", action="from_B", reason="ok", content="b")

        # Reloading is the documented recovery: the loser re-reads and continues.
        w2_reloaded = AuditChain(db_path=db)
        w2_reloaded.record(client_id="b", action="after_reload", reason="ok", content="b")
        assert AuditChain(db_path=db).verify() == (True, "OK")

    def test_sequential_writers_are_unaffected(self, tmp_path):
        db = str(tmp_path / "audit.sqlite")
        _seed(db)
        w1 = AuditChain(db_path=db)
        w1.record(client_id="a", action="one", reason="ok", content="a")
        w2 = AuditChain(db_path=db)          # constructed after w1 appended
        w2.record(client_id="b", action="two", reason="ok", content="b")
        fresh = AuditChain(db_path=db)
        assert fresh.verify() == (True, "OK")
        assert len(fresh._records) == 3

    def test_the_message_names_the_cause_and_the_recovery(self, tmp_path):
        db = str(tmp_path / "audit.sqlite")
        _seed(db)
        w1 = AuditChain(db_path=db)
        w2 = AuditChain(db_path=db)
        w1.record(client_id="a", action="from_A", reason="ok", content="a")
        with pytest.raises(_fork_error()) as exc:
            w2.record(client_id="b", action="from_B", reason="ok", content="b")
        message = str(exc.value).lower()
        assert "fork" in message
        assert "reload" in message


class TestTheConstraintIsStructural:
    def test_the_unique_index_is_per_tenant(self, tmp_path):
        """The index covers (tenant, previous_hash), because a chain is per tenant.

        Uniqueness on previous_hash alone cannot coexist with per-tenant chains:
        every chain starts from the same all-zero GENESIS_HASH, so the second
        tenant's first record would be refused as a fork. See
        tests/test_audit_tenant_scope.py for the cross-tenant cases.
        """
        db = str(tmp_path / "audit.sqlite")
        AuditChain(db_path=db)
        with sqlite3.connect(db) as conn:
            indexes = {
                row[1]: row[2] for row in conn.execute("PRAGMA index_list(audit_records)")
            }
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?",
                ("idx_audit_tenant_previous_hash",),
            ).fetchone()[0]
        assert indexes.get("idx_audit_tenant_previous_hash") == 1, "expected a unique index"
        assert "COALESCE(tenant_id" in sql, (
            "the index must key on a non-null tenant expression, or legacy rows "
            "with tenant_id NULL fall outside the constraint"
        )
        assert "previous_hash" in sql

    def test_the_database_itself_rejects_a_duplicate_predecessor(self, tmp_path):
        # Bypass the Python guard entirely and write through raw SQL. The store
        # must still refuse, which is what makes this construction rather than
        # a check that only holds while the application is the only writer.
        db = str(tmp_path / "audit.sqlite")
        _seed(db)
        with sqlite3.connect(db) as conn:
            genesis = "0" * 64
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO audit_records (timestamp, client_id, action, reason, "
                    "content_hash, record_hash, previous_hash) VALUES "
                    "(0, 'raw', 'raw_insert', 'ok', 'x', 'y', ?)",
                    (genesis,),
                )

    def test_a_store_that_already_contains_a_fork_fails_at_startup(self, tmp_path):
        db = str(tmp_path / "audit.sqlite")
        AuditChain(db_path=db)                      # schema and index, no rows
        with sqlite3.connect(db) as conn:
            conn.execute("DROP INDEX idx_audit_tenant_previous_hash")
            for tag in ("w1", "w2"):
                conn.execute(
                    "INSERT INTO audit_records (timestamp, client_id, action, reason, "
                    "content_hash, record_hash, previous_hash) VALUES "
                    "(0, ?, 'x', 'ok', 'c', ?, '0')",
                    (tag, tag + "_hash"),
                )
        # Two records claim genesis: exactly the state a fork leaves behind.
        with pytest.raises(_fork_error(), match="already contains a fork"):
            AuditChain(db_path=db)
