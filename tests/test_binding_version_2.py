"""Binding version 2: the commitment marker on the record, and a refusal that
does not read as tampering.

Two properties, and the second is the reason the first had to wait for it.

A version 2 record states which form its content_hash is in, so a reader holding
records without the content store can classify every digest instead of guessing.
And a record claiming a version this build does not implement is refused with its
own reason, because before this, an unknown version failed as "tampering
detected": a legitimate future record and an edited one shared a signature.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
"""

import hashlib
import json

import pytest

from custos.audit import (
    COMMITMENT_NONE,
    COMMITMENT_PURGED_V1,
    COMMITMENT_SALTED_V1,
    COMMITMENT_UNSALTED_V0,
    RECORD_BINDING_CURRENT,
    AuditChain,
    AuditRecord,
    preimage_fields,
)
from custos.retention import ContentStore


def _v1_record(**over):
    """A record as the previous build wrote it, for byte-identity checks."""
    fields = dict(
        timestamp=1_700_000_000.0,
        client_id="c",
        action="DENY",
        triggered_rule="rule.x",
        reason="policy",
        content_hash=hashlib.sha256(b"body").hexdigest(),
        record_hash="",
        previous_hash="",
        trace_id="trace-1",
        policy_digest="a" * 64,
        tenant_id="t1",
        binding_version=1,
    )
    fields.update(over)
    return AuditRecord(**fields)


class TestVersionOneStillVerifies:
    def test_a_v1_preimage_is_unchanged_by_this_build(self):
        record = _v1_record()
        expected = {
            "timestamp": record.timestamp,
            "client_id": "c",
            "action": "DENY",
            "triggered_rule": "rule.x",
            "reason": "policy",
            "content_hash": record.content_hash,
            "previous_hash": "GENESIS",
            "policy_digest": "a" * 64,
            "tenant_id": "t1",
            "binding": "v1",
            "trace_id": "trace-1",
        }
        assert preimage_fields(record, "GENESIS") == expected

    def test_a_v2_record_differs_from_the_same_record_at_v1_by_one_key(self):
        v1 = _v1_record()
        v2 = _v1_record(binding_version=2, commitment=COMMITMENT_NONE)
        f1, f2 = preimage_fields(v1, "GENESIS"), preimage_fields(v2, "GENESIS")
        added = set(f2) - set(f1)
        removed = set(f1) - set(f2)
        assert added == {"commitment"}
        assert removed == set()
        # every v1 key keeps its value, so the extension is an append and not a
        # reordering that would invalidate independently recomputed v1 hashes
        assert all(f2[k] == f1[k] for k in f1 if k != "binding")

    def test_the_current_version_is_two(self):
        assert RECORD_BINDING_CURRENT == 2


class TestTheMarkerIsOnTheRecord:
    def test_a_new_record_states_its_form_even_when_it_has_none(self):
        chain = AuditChain()
        record = chain.record(client_id="c", action="ALLOW", reason="ok", content="x")
        assert record.binding_version == 2
        assert record.commitment == COMMITMENT_NONE
        assert "commitment" in preimage_fields(record, chain.GENESIS_HASH)

    def test_the_marker_is_inside_the_hash_not_beside_it(self):
        chain = AuditChain()
        salted = chain.record(
            client_id="c", action="ALLOW", reason="ok", content="x",
            commitment=COMMITMENT_SALTED_V1,
        )
        other = AuditChain()
        unsalted = other.record(
            client_id="c", action="ALLOW", reason="ok", content="x",
            commitment=COMMITMENT_UNSALTED_V0,
        )
        # same body, same everything else: only the form differs, so the hashes
        # must differ or the marker could be relabelled without detection
        assert salted.content_hash == unsalted.content_hash
        assert salted.record_hash != unsalted.record_hash

    def test_a_reader_classifies_a_digest_from_the_record_alone(self):
        chain = AuditChain()
        stored = chain.record(
            client_id="c", action="ALLOW", reason="ok", content="x",
            commitment=COMMITMENT_SALTED_V1,
        )
        purged = chain.record(
            client_id="ops", action="PURGE", reason="erasure", content="x",
            commitment=COMMITMENT_PURGED_V1,
        )
        # no side store consulted: the forms are in the records
        assert stored.to_dict()["commitment"] == "salted-v1"
        assert purged.to_dict()["commitment"] == "purged-v1"

    def test_an_unknown_marker_is_refused_rather_than_recorded(self):
        chain = AuditChain()
        with pytest.raises(ValueError) as exc:
            chain.record(
                client_id="c", action="ALLOW", reason="ok", content="x",
                commitment="salted-v9-typo",
            )
        assert "unknown commitment form" in str(exc.value)

    def test_the_store_and_the_record_agree_on_the_form(self, tmp_path):
        store = ContentStore(str(tmp_path / "c.sqlite"))
        chain = AuditChain()
        record = store.put_and_record(
            "transfer approved", chain=chain, client_id="c", action="ALLOW",
            reason="ok",
        )
        assert record.commitment == COMMITMENT_SALTED_V1
        assert store.marker(record.content_hash) == "salted-v1"

        legacy = store.put_and_record(
            "older content", chain=chain, client_id="c", action="ALLOW",
            reason="ok", legacy=True,
        )
        assert legacy.commitment == COMMITMENT_UNSALTED_V0
        assert store.marker(legacy.content_hash) == "unsalted-v0"

    def test_a_purge_attestation_carries_the_purged_form(self, tmp_path):
        store = ContentStore(str(tmp_path / "c.sqlite"))
        chain = AuditChain()
        record = store.put_and_record(
            "erase me", chain=chain, client_id="c", action="ALLOW", reason="ok"
        )
        store.purge(record.content_hash, chain=chain, client_id="ops", reason="erasure")
        assert chain._records[-1].commitment == COMMITMENT_PURGED_V1


class TestAnUnknownVersionIsNotTampering:
    def _future_record(self):
        chain = AuditChain()
        record = chain.record(client_id="c", action="ALLOW", reason="ok", content="x")
        # rewrite as if a newer writer had produced it
        record.binding_version = 7
        record.commitment = COMMITMENT_SALTED_V1
        return record, chain

    def test_verify_names_the_version_instead_of_the_attack(self):
        record, chain = self._future_record()
        ok, message = chain.verify()
        assert ok is False
        assert "binding version 7" in message
        assert "not a tampering finding" in message
        assert "tampering detected" not in message

    def test_a_future_record_does_not_report_as_an_edited_one(self):
        _, chain = self._future_record()
        _, version_message = chain.verify()
        # a separate chain, one field actually edited at the current version
        edited = AuditChain()
        edited.record(client_id="c", action="ALLOW", reason="ok", content="x")
        edited._records[0].reason = "rewritten"
        _, edited_message = edited.verify()
        assert "tampering detected" in edited_message
        assert "tampering detected" not in version_message
        assert version_message != edited_message

    def test_the_hash_is_refused_rather_than_computed(self):
        # Resolved through the module at call time: another test module reloads
        # custos.audit, so a class captured at import can be a different object
        # from the one raised, and pytest.raises would miss it while the code is
        # behaving correctly. Same trap the single-writer guard documents.
        import custos.audit as audit_module

        record, _chain = self._future_record()
        with pytest.raises(audit_module.UnknownBindingVersion) as exc:
            audit_module.compute_record_hash(record, AuditChain.GENESIS_HASH)
        assert "7" in str(exc.value)

    def test_a_tombstone_from_a_future_version_is_distinguishable(self):
        """The case the dispatch exists for: a legitimate later record is not an
        attack, and an operator reading only a boolean cannot tell them apart."""
        record, chain = self._future_record()
        ok, message = chain.verify()
        assert ok is False
        assert "does not implement (up to 2)" in message
        assert "verify with a build that implements version 7" in message


class TestItSurvivesAStore:
    def test_the_form_round_trips_through_sqlite(self, tmp_path):
        path = str(tmp_path / "audit.sqlite")
        chain = AuditChain(db_path=path)
        chain.record(
            client_id="c", action="ALLOW", reason="ok", content="x",
            commitment=COMMITMENT_SALTED_V1,
        )
        reopened = AuditChain(db_path=path)
        assert reopened._records[-1].commitment == COMMITMENT_SALTED_V1
        assert reopened.verify() == (True, "OK")

    def test_a_genuine_v1_row_verifies_under_this_build(self, tmp_path):
        """The compatibility claim: a store holding version 1 rows, written by
        build 1, opens and verifies under build 2 unchanged."""
        import sqlite3

        path = str(tmp_path / "legacy.sqlite")
        AuditChain(db_path=path)  # creates the schema
        v1 = _v1_record(
            content_hash=hashlib.sha256(b"x").hexdigest(),
            binding_version=1,
        )
        v1.previous_hash = AuditChain.GENESIS_HASH
        v1.record_hash = hashlib.sha256(
            json.dumps(
                {
                    "timestamp": v1.timestamp,
                    "client_id": v1.client_id,
                    "action": v1.action,
                    "triggered_rule": v1.triggered_rule,
                    "reason": v1.reason,
                    "content_hash": v1.content_hash,
                    "previous_hash": AuditChain.GENESIS_HASH,
                    "policy_digest": v1.policy_digest,
                    "tenant_id": v1.tenant_id,
                    "binding": "v1",
                    "trace_id": v1.trace_id,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO audit_records (timestamp, client_id, action,"
                " triggered_rule, reason, content_hash, record_hash, previous_hash,"
                " trace_id, policy_digest, tenant_id, binding_version, commitment)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    v1.timestamp, v1.client_id, v1.action, v1.triggered_rule,
                    v1.reason, v1.content_hash, v1.record_hash, v1.previous_hash,
                    v1.trace_id, v1.policy_digest, v1.tenant_id, 1, None,
                ),
            )
        reopened = AuditChain(db_path=path)
        # no commitment column value, so the form reads as none, and the hash is
        # recomputed exactly as build 1 computed it
        assert reopened._records[0].commitment == COMMITMENT_NONE
        assert reopened.verify() == (True, "OK")

    def test_downgrading_a_stored_row_to_v1_is_detected(self, tmp_path):
        """The converse, and it is not symmetric: a version 2 row relabelled as
        version 1 loses the commitment key from its preimage, so its stored hash
        no longer matches. Editing the version field is an edit."""
        import sqlite3

        path = str(tmp_path / "downgrade.sqlite")
        chain = AuditChain(db_path=path)
        chain.record(client_id="c", action="ALLOW", reason="ok", content="x")
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE audit_records SET binding_version = 1")
        reopened = AuditChain(db_path=path)
        ok, message = reopened.verify()
        assert ok is False and "tampering" in message
