"""Cross-tenant behaviour of the audit chain's single-writer constraint.

Item 5's fork tests were all single-chain: the raw-SQL refusal, the eight-case
mutation check and the two-writer transcript each prove the constraint works
against a competing writer on one chain, and none of them constructs two
tenants, so none of them could have surfaced the cross-tenant collision. These
cases are the missing dimension.

Two facts drive them. Every chain begins from the same all-zero GENESIS_HASH, so
uniqueness on previous_hash alone refuses the second tenant's first record. And
the loader returned every row in the store, so a second tenant's chain contained
the first tenant's records and verified green while doing it.
"""

import sqlite3

import pytest

from custos.audit import AuditChain


def _fork_error():
    """Resolve the error class at call time.

    Another module in this suite reloads custos.audit, which rebinds the class.
    A module-scope import compares against a stale one and the assertion stops
    meaning anything, silently.
    """
    from custos.audit import ChainForkError

    return ChainForkError


def _seed(db, tenant):
    chain = AuditChain(db_path=db, tenant_id=tenant)
    chain.record(
        client_id=tenant,
        action=f"{tenant}_first",
        reason="seed",
        content="payload",
        tenant_id=tenant,
    )


class TestTwoTenantsOneStore:
    def test_each_chain_loads_only_its_own_records(self, tmp_path):
        db = str(tmp_path / "shared.sqlite")
        _seed(db, "acme")
        _seed(db, "beta")

        acme = AuditChain(db_path=db, tenant_id="acme")
        beta = AuditChain(db_path=db, tenant_id="beta")

        assert [r.tenant_id for r in acme._records] == ["acme"]
        assert [r.tenant_id for r in beta._records] == ["beta"]

    def test_the_second_tenant_can_be_seeded_at_all(self, tmp_path):
        """The regression: this used to fail with UNIQUE constraint failed."""
        db = str(tmp_path / "shared.sqlite")
        _seed(db, "acme")
        _seed(db, "beta")            # would raise before the composite index

        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT tenant_id, previous_hash FROM audit_records ORDER BY id"
            ).fetchall()

        assert [r[0] for r in rows] == ["acme", "beta"]
        assert rows[0][1] == rows[1][1] == "0" * 64, (
            "both first records must claim the same genesis, which is exactly "
            "why uniqueness has to be per tenant"
        )

    def test_both_chains_verify_independently(self, tmp_path):
        db = str(tmp_path / "shared.sqlite")
        _seed(db, "acme")
        _seed(db, "beta")

        assert AuditChain(db_path=db, tenant_id="acme").verify() == (True, "OK")
        assert AuditChain(db_path=db, tenant_id="beta").verify() == (True, "OK")

    def test_one_tenant_writing_does_not_disturb_the_other(self, tmp_path):
        db = str(tmp_path / "shared.sqlite")
        _seed(db, "acme")
        _seed(db, "beta")
        acme_before = AuditChain(db_path=db, tenant_id="acme").verify()

        AuditChain(db_path=db, tenant_id="beta").record(
            client_id="beta",
            action="beta_second",
            reason="more",
            content="payload",
            tenant_id="beta",
        )

        assert AuditChain(db_path=db, tenant_id="acme").verify() == acme_before
        assert len(AuditChain(db_path=db, tenant_id="beta")._records) == 2


class TestTheConstraintStillHoldsWithinOneTenant:
    def test_a_stale_writer_for_the_same_tenant_is_refused(self, tmp_path):
        """The composite index must not weaken the per-chain guarantee."""
        db = str(tmp_path / "shared.sqlite")
        _seed(db, "acme")

        w1 = AuditChain(db_path=db, tenant_id="acme")
        w2 = AuditChain(db_path=db, tenant_id="acme")   # both loaded the same head
        w1.record(
            client_id="acme", action="from_w1", reason="r", content="c", tenant_id="acme"
        )
        with pytest.raises(_fork_error()):
            w2.record(
                client_id="acme", action="from_w2", reason="r", content="c",
                tenant_id="acme",
            )

        assert AuditChain(db_path=db, tenant_id="acme").verify() == (True, "OK")

    def test_a_raw_insert_claiming_a_claimed_predecessor_is_refused(self, tmp_path):
        """Proves the refusal is the database, not a Python check in the append path."""
        db = str(tmp_path / "shared.sqlite")
        _seed(db, "acme")
        # The seed already claims the genesis predecessor. A second record for
        # the same tenant claiming it again is a fork, and SQLite rather than
        # the append path has to be the thing that refuses it.
        with sqlite3.connect(db) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO audit_records (timestamp, client_id, action, reason, "
                    "content_hash, record_hash, previous_hash, tenant_id) VALUES "
                    "(0, 'acme', 'sneaked', 'r', 'c', 'sneaked_hash', ?, 'acme')",
                    (AuditChain.GENESIS_HASH,),
                )

    def test_the_same_predecessor_across_tenants_is_allowed(self, tmp_path):
        """What the per-tenant index buys: genesis is shared, chains are not."""
        db = str(tmp_path / "shared.sqlite")
        with sqlite3.connect(db) as conn:
            AuditChain(db_path=db, tenant_id="acme")     # schema
        with sqlite3.connect(db) as conn:
            for tenant in ("acme", "beta"):
                conn.execute(
                    "INSERT INTO audit_records (timestamp, client_id, action, reason, "
                    "content_hash, record_hash, previous_hash, tenant_id) VALUES "
                    "(0, ?, 'x', 'r', 'c', ?, '0', ?)",
                    (tenant, tenant + "_hash", tenant),
                )
        with sqlite3.connect(db) as conn:
            claimed = conn.execute(
                "SELECT COUNT(*) FROM audit_records WHERE previous_hash = '0'"
            ).fetchone()[0]
        assert claimed == 2, "one genesis predecessor per tenant, two tenants"


class TestUnscopedOpen:
    def test_a_single_tenant_store_still_opens_unscoped(self, tmp_path):
        db = str(tmp_path / "legacy.sqlite")
        _seed(db, "acme")
        chain = AuditChain(db_path=db)               # legacy path, no scope
        assert len(chain._records) == 1
        assert chain.verify() == (True, "OK")

    def test_an_unscoped_open_of_two_tenants_is_refused_rather_than_interleaved(
        self, tmp_path
    ):
        db = str(tmp_path / "shared.sqlite")
        _seed(db, "acme")
        _seed(db, "beta")

        with pytest.raises(_fork_error()) as excinfo:
            AuditChain(db_path=db)

        message = str(excinfo.value)
        assert "more than one tenant" in message
        assert "acme" in message and "beta" in message
        assert "tenant_id" in message
