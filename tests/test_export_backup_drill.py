"""The export/backup record stays bound to the code that produced it.

The document describes a measurement of what a restore does to an erasure. Two
things make it worth anything: the negative result is in it as a transcript
rather than a summary, and the lines in that transcript are lines the committed
script prints. These guards hold both, so the record fails the suite rather than
aging into a claim nobody can re-run.
"""

import pathlib
import re

DOC = pathlib.Path("docs/restore-drills/2026-11-06-export-backup.md")
SCRIPT = pathlib.Path("scripts/drills/phase11_export_backup.py")


def _doc() -> str:
    """Whitespace-normalised: prose wraps mid-phrase, and a guard that only
    matches an unwrapped line fails on layout rather than on content."""
    return " ".join(DOC.read_text(encoding="utf-8").split())


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


class TestTheRecordIsBoundToItsScript:
    def test_the_document_names_the_script_a_reader_runs(self):
        doc = _doc()
        assert "scripts/drills/phase11_export_backup.py" in doc
        assert SCRIPT.exists(), "the driver the record names must be in the repository"

    def test_every_quoted_result_line_is_one_the_script_prints(self):
        doc = _doc()
        quoted = [
            "RESULT records before backup:",
            "RESULT backup-1 audit:",
            "RESULT live c1 status after purge:",
            "RESULT body bytes left in the live content store:",
            "RESULT body bytes inside backup-2:",
            "RESULT live export:",
            "RESULT restored body reads back:",
            "RESULT purge attestations in the restored chain:",
            "RESULT split restore record forms:",
            "RESULT exports disagree on:",
        ]
        script = _script()
        for line in quoted:
            assert line in doc, f"{line} is quoted in the record but not found there"
            assert line in script, f"{line} is quoted in the record but the script never prints it"

    def test_the_document_quotes_the_checks_the_script_computes(self):
        """The seven booleans at the end are the acceptance. If the script gains
        or loses one, the record says something the run did not."""
        doc = _doc()
        script = _script()
        labels = [
            "live purge holds in the store bytes",
            "post-purge backup carries no body",
            "export carries forms, never bodies",
            "restore brings the body back",
            "restored commitment opens",
            "restored chain verifies without the attestation",
            "exports disagree after the restore",
            "split restore does not reconcile clean",
            "split restore names the unattested purge",
            "live and restored pairs reconcile clean",
        ]
        for label in labels:
            assert label in script, f"{label} is not a check the script performs"
            assert label in doc, f"{label} is performed but not recorded"

    def test_it_carries_the_negative_result_rather_than_a_summary(self):
        """A restore that undoes an erasure is the finding. It has to be in the
        record as an observation, next to the lines that produced it."""
        doc = _doc()
        assert "## The negative result, stated" in doc
        assert "unattested-purge" in doc
        assert "RESULT restored body reads back: True" in doc
        assert "RESULT purge attestations in the restored chain: 0" in doc
        assert "purged → present" in doc or "purged -> present" in doc


class TestTheRecoveryWindowIsStatedPerStore:
    def test_all_three_units_and_their_windows_are_named(self):
        doc = _doc()
        assert "## Recovery window, per store" in doc
        for unit in ("content body", "salt and commitment", "purge attestation"):
            assert unit in doc, f"{unit} is missing from the window table"
        assert "unrecoverable after" in doc

    def test_the_asymmetry_is_stated_rather_than_left_to_the_reader(self):
        """The body's window and the attestation's window run in opposite
        directions. A table without that sentence invites the reading that one
        backup satisfies both."""
        doc = _doc()
        assert "inverse of the body" in doc
        assert "cannot satisfy both halves of an erasure" in doc

    def test_the_salt_shares_the_body_row_and_says_so(self):
        """Precision that matters: no backup recovers the salt without the body,
        so the exposure is one unit."""
        doc = _doc()
        assert "same row" in doc
        assert "one unit" in doc


class TestTheRecordKeepsItsLimits:
    def test_it_does_not_claim_backup_completeness(self):
        doc = _doc()
        assert "## What this run does not establish" in doc
        assert "does not establish that a backup is complete" in doc
        assert "external head anchoring" in doc

    def test_it_does_not_claim_the_served_path_purges(self):
        """The service stores nothing, so the drill binds content through the
        store API. Describing that as service behaviour would be the overclaim."""
        doc = _doc()
        assert "commitment: none" in doc
        assert "137" in doc, "the served-path wiring gap must stay filed, not smoothed"
        assert "136" in doc, "the split-restore defect must stay filed, not smoothed"


class TestTheScriptRefusesRatherThanPassesOnNothing:
    """The rule that came out of the InMemoryBackend pass: a drill asserts its
    preconditions and fails when they do not hold, instead of reporting green."""

    def test_failures_reach_the_exit_code(self):
        script = _script()
        assert "failed = [label for label, passed in checks if not passed]" in script
        assert "return 0 if not failed else 1" in script

    def test_the_store_is_searched_by_bytes_not_through_the_query_view(self):
        """A row deleted in the query view can leave its bytes in the file, and
        the file is what a copy copies."""
        script = _script()
        assert "read_bytes().count(" in script
        assert "not a query through the store" in script

class TestTheRecordIsCompleteAsWellAsAccurate:
    """The guard above checks that every line the record quotes is a line the script
    prints. It does not check the other direction, so a transcript could omit a line
    and stay green: the same one-directional shape as the count check, found by
    applying the rule that a guard is proven by reverting its claim.

    Measured when this was added: every distinct RESULT prefix the script can print
    appears in the record, so the reverse direction holds today and can be enforced
    rather than left to whoever regenerates the transcript."""

    def test_every_result_the_script_can_print_is_in_the_record(self):
        script = SCRIPT.read_text(encoding="utf-8")
        doc = _doc()
        prefixes = {
            m.group(1).strip().rstrip(": ")
            for m in re.finditer(r'RESULT ([^{":]+)', script)
        }
        missing = sorted(p for p in prefixes if p and p not in doc)
        assert not missing, f"the script prints lines the record does not carry: {missing}"
