"""The purge path: content separation, salted commitments, and what a purge
actually deletes.

The property under test is not "content is gone". It is that a reader can tell
the difference between three states afterwards (present, purged, never held),
that the chain verifies record for record across the deletion, and that an
unsalted commitment can never be mistaken for a salted one.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
"""

import hashlib
import sqlite3

import pytest

from custos.audit import AuditChain
from custos.retention import (
    MARKER_SALTED,
    ContentPurged,
    ContentStore,
    PurgeRefused,
    _commitment,
)


@pytest.fixture()
def store(tmp_path):
    return ContentStore(str(tmp_path / "content.sqlite"))


@pytest.fixture()
def chain(tmp_path):
    return AuditChain()


BODY = "the wire transfer should skip the approval queue"


class TestTheRecordHashDoesNotChange:
    def test_a_stored_body_hashes_to_the_value_the_record_binds(self, store, chain):
        content_hash = store.put(BODY)
        record = chain.record(client_id="c", action="ALLOW", reason="ok", content=BODY)
        assert content_hash == record.content_hash
        assert content_hash == hashlib.sha256(BODY.encode()).hexdigest()

    def test_the_side_store_is_the_only_place_the_body_lives(self, store, chain, tmp_path):
        content_hash = store.put(BODY)
        chain.record(client_id="c", action="ALLOW", reason="ok", content=BODY)
        with sqlite3.connect(tmp_path / "content.sqlite") as conn:
            assert conn.execute(
                "SELECT body FROM content_bodies WHERE content_hash=?", (content_hash,)
            ).fetchone()[0] == BODY
        # the chain record carries the hash and never the bytes
        assert "wire transfer" not in str(chain._records[-1].to_dict())


class TestTheCommitmentIsSalted:
    def test_identical_bodies_get_different_salts_and_different_digests(self, tmp_path):
        a = ContentStore(str(tmp_path / "a.sqlite"))
        b = ContentStore(str(tmp_path / "b.sqlite"))
        ha, hb = a.put(BODY), b.put(BODY)
        assert ha == hb  # identity is the content, as the record expects
        assert a.marker(ha) == "salted-v1"
        with sqlite3.connect(str(tmp_path / "a.sqlite")) as ca, sqlite3.connect(
            str(tmp_path / "b.sqlite")
        ) as cb:
            salt_a, dig_a = ca.execute(
                "SELECT salt, commitment FROM content_bodies"
            ).fetchone()
            salt_b, dig_b = cb.execute(
                "SELECT salt, commitment FROM content_bodies"
            ).fetchone()
        assert salt_a != salt_b
        assert dig_a != dig_b, "a stored digest that is equal across writers is linkable"

    def test_the_marker_participates_in_the_digest(self):
        salt = b"\x01" * 32
        assert _commitment(BODY, salt) != _commitment(BODY, None)
        # and a bare digest of the body is never what the salted form produces
        assert hashlib.sha256(BODY.encode()).hexdigest() != _commitment(BODY, salt)

    def test_the_marker_is_what_makes_the_two_forms_differ(self):
        # Same body, no salt, but the salted marker: if the marker were merely
        # stored alongside the digest rather than digested with it, these two
        # would be equal and an unsalted commitment could be relabelled as
        # salted by anyone who knew the body.
        salted_marker_digest = hashlib.sha256(
            MARKER_SALTED + BODY.encode()
        ).hexdigest()
        assert _commitment(BODY, None) != salted_marker_digest

    def test_an_unsalted_commitment_is_readable_as_unsalted(self, store):
        content_hash = store.put_legacy(BODY)
        assert store.marker(content_hash) == "unsalted-v0"
        with sqlite3.connect(store._path) as conn:
            stored = conn.execute(
                "SELECT salt, commitment FROM content_bodies"
            ).fetchone()
        assert stored[0] is None
        # the digest is the unsalted form exactly, so it is reproducible by
        # anyone holding the body and is never confused with the salted one
        assert stored[1] == _commitment(BODY, None)
        assert stored[1] != _commitment(BODY, b"\x00" * 32)

    def test_a_salted_commitment_is_readable_as_salted(self, store):
        content_hash = store.put(BODY)
        assert store.marker(content_hash) == "salted-v1"
        with sqlite3.connect(store._path) as conn:
            salt, commitment = conn.execute(
                "SELECT salt, commitment FROM content_bodies"
            ).fetchone()
        assert len(salt) == 32
        assert commitment == _commitment(BODY, salt)
        # the unsalted form of the same body is a different digest, and knowing
        # the body alone does not reproduce what the store holds
        assert commitment != _commitment(BODY, None)


class TestVerifyingACommitment:
    def test_the_right_body_opens_the_commitment(self, store):
        content_hash = store.put(BODY)
        assert store.verify_commitment(content_hash, BODY) is True

    def test_the_wrong_body_does_not(self, store):
        content_hash = store.put(BODY)
        assert store.verify_commitment(content_hash, BODY + " ") is False


class TestThePurge:
    def test_it_deletes_body_and_salt_together(self, store, chain):
        content_hash = store.put(BODY)
        store.purge(content_hash, chain=chain, client_id="ops", reason="gdpr erasure")
        with sqlite3.connect(store._path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM content_bodies").fetchone()[0] == 0
            # nothing left in the side store that could open the commitment
            assert conn.execute(
                "SELECT COUNT(*) FROM content_bodies WHERE salt IS NOT NULL"
            ).fetchone()[0] == 0

    def test_the_chain_still_verifies_across_the_deletion(self, store, chain):
        content_hash = store.put(BODY)
        before = len(chain._records)
        store.purge(content_hash, chain=chain, client_id="ops", reason="erasure")
        assert len(chain._records) == before + 1
        assert chain.verify() == (True, "OK")

    def test_the_attestation_binds_the_content_it_deleted(self, store, chain):
        content_hash = store.put(BODY)
        attestation = store.purge(
            content_hash, chain=chain, client_id="ops", reason="erasure"
        )
        record = chain._records[-1]
        assert record.action == "PURGE"
        assert record.content_hash == content_hash
        assert record.record_hash == attestation
        assert store.purge_record(content_hash)["attestation_hash"] == attestation
        # the attestation is a record like any other: no field holds the body
        assert "wire transfer" not in str(record.to_dict())

    def test_status_distinguishes_purged_from_never_held(self, store, chain):
        content_hash = store.put(BODY)
        assert store.status(content_hash) == "present"
        store.purge(content_hash, chain=chain, client_id="ops", reason="erasure")
        assert store.status(content_hash) == "purged"
        assert store.status("0" * 64) == "unknown"
        assert store.marker(content_hash) == "purged"


class TestTheRefusals:
    def test_a_second_purge_names_the_first(self, store, chain):
        content_hash = store.put(BODY)
        store.purge(content_hash, chain=chain, client_id="ops", reason="erasure")
        with pytest.raises(ContentPurged) as exc:
            store.purge(content_hash, chain=chain, client_id="ops", reason="erasure")
        assert "already purged" in str(exc.value)

    def test_purging_what_the_store_never_held_is_refused(self, store, chain):
        with pytest.raises(PurgeRefused) as exc:
            store.purge("0" * 64, chain=chain, client_id="ops", reason="erasure")
        assert "never held" in str(exc.value)

    def test_reading_purged_content_says_so_rather_than_returning_empty(self, store, chain):
        content_hash = store.put(BODY)
        store.purge(content_hash, chain=chain, client_id="ops", reason="erasure")
        with pytest.raises(ContentPurged) as exc:
            store.open_body(content_hash)
        assert "purged at" in str(exc.value)

    def test_verifying_purged_content_is_not_a_failed_integrity_check(self, store, chain):
        content_hash = store.put(BODY)
        store.purge(content_hash, chain=chain, client_id="ops", reason="erasure")
        with pytest.raises(ContentPurged):
            store.verify_commitment(content_hash, BODY)

    def test_a_purged_body_cannot_be_restored_by_re_offering_it(self, store, chain):
        content_hash = store.put(BODY)
        store.purge(content_hash, chain=chain, client_id="ops", reason="erasure")
        with pytest.raises(ContentPurged) as exc:
            store.put(BODY)
        assert "purged at" in str(exc.value)


class TestThePurgeDrillStaysTrue:
    """The transcript is evidence, so bind it to the strings it quotes.

    Same reason as the audit drill guard: a record that quotes a refusal the code
    no longer raises, or that drops the section naming its own residual, reads as
    a measurement and is a memory.
    """

    DOC = "docs/restore-drills/2026-11-06-purge-path.md"

    def _doc(self):
        import pathlib

        return pathlib.Path(self.DOC).read_text()

    def test_it_quotes_the_states_and_refusals_the_code_produces(self):
        from custos.retention import STATUS_PRESENT, STATUS_PURGED, STATUS_UNKNOWN

        doc = self._doc()
        for state in (STATUS_PRESENT, STATUS_PURGED, STATUS_UNKNOWN):
            assert state in doc, f"the drill no longer shows the {state} state"
        # the two refusal sentences the run quotes, as the code words them
        assert "was purged at" in doc
        assert "never held" in doc
        assert "RESULT chain after purge: (True, 'OK')" in doc

    def test_the_attestation_states_its_form_inside_the_preimage(self):
        """The record side, which the original transcript could not show.

        A reader holding records without the side store has to be able to tell a
        deletion from a mismatch. ``action: PURGE`` is a label; the commitment
        form is inside the hash, so it cannot be relabelled after the fact.
        """
        import tempfile

        from custos.audit import COMMITMENT_PURGED_V1, preimage_fields

        with tempfile.TemporaryDirectory() as d:
            store = ContentStore(f"{d}/content.sqlite")
            chain = AuditChain(db_path=f"{d}/audit.sqlite")
            content_hash = store.put_and_record(
                "erase me", chain=chain, client_id="c", action="ALLOW", reason="ok"
            ).content_hash
            store.purge(content_hash, chain=chain, client_id="ops", reason="erasure")

        attestation = chain._records[-1]
        assert attestation.commitment == COMMITMENT_PURGED_V1
        fields = preimage_fields(attestation, attestation.previous_hash)
        assert fields["commitment"] == COMMITMENT_PURGED_V1
        # the purged record keeps the form it was stored in, so the pair reads
        # salted-then-purged rather than being rewritten to the outcome
        assert chain._records[0].commitment == "salted-v1"

    def test_the_rerun_has_its_own_record(self):
        """The re-execution is its own document, not the earlier transcript with
        a later section spliced into it. A transcript with an appendix is no
        longer a transcript: a reader cannot tell which build produced which
        lines, and the earlier record stops being evidence of the build it ran on.
        """
        import pathlib

        rerun = pathlib.Path("docs/restore-drills/2026-11-06-purge-path-post-marker.md")
        assert rerun.exists(), "the post-marker run must be its own record"
        text = rerun.read_text()
        assert "2b9296a" in text
        assert "RESULT attestation preimage carries commitment: True = purged-v1" in text
        assert "RESULT attestation is a deletion, readable from the record alone: True" in text
        # the script a reader is told to run is in the repository, and the
        # temporary path it replaced is named only as history
        assert pathlib.Path("scripts/purge_path_drill.py").exists()
        assert "python3 scripts/purge_path_drill.py" in text
        assert "/tmp/purgedrill/run.py" not in text

    def test_the_earlier_transcript_is_left_as_recorded(self):
        """Frozen records stay frozen: the older document is unchanged apart from
        a pointer, and it still carries the run it actually performed."""
        doc = self._doc()
        assert "## Re-run after the marker" not in doc
        assert "2026-11-06-purge-path-post-marker.md" in doc, "the pointer is the only addition"
        # the temporary path it named is left in place, as history, in this file
        assert "/tmp/purgedrill/run.py" in doc

    def test_it_keeps_the_section_naming_the_copy_problem(self):
        doc = self._doc()
        assert "## What the run does not establish" in doc
        # the residual that a purge cannot reach a backup taken before it, which
        # is the whole reason the run copies the store before deleting
        assert "The copy problem" in doc
        assert "restored commitment opens: True" in doc
