"""Issue 136: a restore that contradicts the records is reported by name.

The defect these tests hold shut: restoring an audit store to a point before an
erasure, beside a content store that is past it, produced a chain that verified
green while its records said the content was held and its store said it was
purged. Nothing compared them, so the contradiction was silent.

Two properties are asserted together and must not be traded for each other: the
disagreement is reported, and verify() still says the chain is green, because a
green chain is a statement about record linkage and not about a store.
"""

import shutil

import pytest

from custos.audit import AuditChain
from custos.retention import (
    FINDING_BODY_MISSING,
    FINDING_UNEFFECTED_PURGE,
    FINDING_UNATTESTED_PURGE,
    ContentPurged,
    ContentStore,
    reconcile,
)


def _chain(tmp_path, name="audit.sqlite"):
    return AuditChain(db_path=str(tmp_path / name))


def _store(tmp_path, name="content.sqlite"):
    return ContentStore(str(tmp_path / name))


def _record(chain, store, body, client_id="t"):
    return store.put_and_record(body, chain=chain, client_id=client_id, action="ALLOW", reason="r")


class TestAConsistentPair:
    def test_a_held_body_agrees(self, tmp_path):
        chain, store = _chain(tmp_path), _store(tmp_path)
        _record(chain, store, "held body")
        report = reconcile(chain._records, store)
        assert report.ok, report.describe()
        assert report.findings == []

    def test_a_purged_body_agrees_because_the_attestation_is_there(self, tmp_path):
        chain, store = _chain(tmp_path), _store(tmp_path)
        rec = _record(chain, store, "to be purged")
        store.purge(rec.content_hash, chain=chain, client_id="ops", reason="erasure")
        report = reconcile(chain._records, store)
        assert report.ok, report.describe()

    def test_a_record_that_claims_no_content_is_never_compared(self, tmp_path):
        """commitment:none says the record binds no stored content, so the store
        has nothing to answer for and an empty store is not a defect."""
        chain, store = _chain(tmp_path), _store(tmp_path)
        chain.record(client_id="t", action="DENY", reason="no content bound", content="")
        report = reconcile(chain._records, store)
        assert report.ok, report.describe()
        assert report.digests_examined == 0


class TestTheSplitRestoreIsNamed:
    """The measured state from phase 11: audit store rolled back, content store
    left live. The chain is green, the record says salted-v1, the store says
    purged, and this is the finding that used to be silent."""

    def _split(self, tmp_path):
        chain, store = _chain(tmp_path), _store(tmp_path)
        rec = _record(chain, store, "erased under a restored chain")
        shutil.copy2(tmp_path / "audit.sqlite", tmp_path / "audit-pre-purge.sqlite")
        shutil.copy2(tmp_path / "content.sqlite", tmp_path / "content-pre-purge.sqlite")
        store.purge(rec.content_hash, chain=chain, client_id="ops", reason="erasure")

        shutil.copy2(tmp_path / "audit-pre-purge.sqlite", tmp_path / "audit-restored.sqlite")
        restored_chain = AuditChain(db_path=str(tmp_path / "audit-restored.sqlite"))
        return restored_chain, store, rec

    def test_the_contradiction_is_reported_by_name(self, tmp_path):
        restored_chain, store, rec = self._split(tmp_path)
        report = reconcile(restored_chain._records, store)
        assert not report.ok
        assert [f.kind for f in report.findings] == [FINDING_UNATTESTED_PURGE]
        assert report.findings[0].content_hash == rec.content_hash
        # The record index is carried so a reader can go straight to it.
        assert report.findings[0].record_indexes == (0,)

    def test_the_chain_still_verifies_green(self, tmp_path):
        """The fix must not be 'make verify() fail'. That would collapse two
        statements into one, which is the error the version dispatch already
        cost a round to separate."""
        restored_chain, _, _ = self._split(tmp_path)
        assert restored_chain.verify() == (True, "OK")
        # And reconciliation has no opinion on linkage either.
        report = reconcile(restored_chain._records, store=_store(tmp_path))
        assert [f.kind for f in report.findings] == [FINDING_UNATTESTED_PURGE]

    def test_the_finding_says_what_is_wrong_without_being_asked(self, tmp_path):
        restored_chain, store, _ = self._split(tmp_path)
        text = reconcile(restored_chain._records, store).describe()
        assert FINDING_UNATTESTED_PURGE in text
        assert "no record attests the purge" in text


class TestTheOtherTwoDirections:
    def test_a_body_lost_without_a_purge_is_missing_not_purged(self, tmp_path):
        """Absence and deletion are different findings; the store distinguishes
        them for purged content and the reconciliation must keep that."""
        chain, store = _chain(tmp_path), _store(tmp_path)
        _record(chain, store, "never stored here")
        empty = _store(tmp_path, name="other-content.sqlite")
        report = reconcile(chain._records, empty)
        assert [f.kind for f in report.findings] == [FINDING_BODY_MISSING]

    def test_a_content_store_rolled_back_under_the_attestation_is_reported(self, tmp_path):
        """The mirror restore: the chain recorded the purge and the store still
        holds the body, so the attestation describes a store that is not this
        one. Deleting the attestation would be a splice; reporting it is not."""
        chain, store = _chain(tmp_path), _store(tmp_path)
        rec = _record(chain, store, "restored content store")
        shutil.copy2(tmp_path / "content.sqlite", tmp_path / "content-pre-purge.sqlite")
        store.purge(rec.content_hash, chain=chain, client_id="ops", reason="erasure")
        shutil.copy2(tmp_path / "content-pre-purge.sqlite", tmp_path / "content-restored.sqlite")
        restored_store = ContentStore(str(tmp_path / "content-restored.sqlite"))
        report = reconcile(chain._records, restored_store)
        assert [f.kind for f in report.findings] == [FINDING_UNEFFECTED_PURGE]

    def test_two_digests_produce_two_findings_not_one(self, tmp_path):
        chain, store = _chain(tmp_path), _store(tmp_path)
        a = _record(chain, store, "first")
        b = _record(chain, store, "second")
        shutil.copy2(tmp_path / "audit.sqlite", tmp_path / "audit-pre.sqlite")
        for rec in (a, b):
            store.purge(rec.content_hash, chain=chain, client_id="ops", reason="erasure")
        shutil.copy2(tmp_path / "audit-pre.sqlite", tmp_path / "audit-restored.sqlite")
        restored = AuditChain(db_path=str(tmp_path / "audit-restored.sqlite"))
        report = reconcile(restored._records, store)
        assert report.by_kind() == {FINDING_UNATTESTED_PURGE: 2}
        assert len(report.findings) == 2


class TestReconcileIsReadOnly:
    def test_it_writes_nothing(self, tmp_path):
        chain, store = _chain(tmp_path), _store(tmp_path)
        rec = _record(chain, store, "unchanged")
        before = (
            (tmp_path / "content.sqlite").read_bytes(),
            (tmp_path / "audit.sqlite").read_bytes(),
        )
        reconcile(chain._records, store)
        after = (
            (tmp_path / "content.sqlite").read_bytes(),
            (tmp_path / "audit.sqlite").read_bytes(),
        )
        assert before == after
        assert store.open_body(rec.content_hash) == "unchanged"

    def test_it_does_not_open_bodies(self, tmp_path):
        """A body that cannot be opened must not make the comparison fail: the
        reconciliation is about claims and status, and reading content to answer
        it would put the content back in a code path that only needs hashes."""
        chain, store = _chain(tmp_path), _store(tmp_path)
        rec = _record(chain, store, "purged body")
        store.purge(rec.content_hash, chain=chain, client_id="ops", reason="erasure")
        with pytest.raises(ContentPurged):
            store.open_body(rec.content_hash)
        assert reconcile(chain._records, store).ok
