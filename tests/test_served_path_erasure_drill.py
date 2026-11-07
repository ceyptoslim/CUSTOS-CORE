"""The erasure record and the design note stay bound to the code that produced them.

Two documents describe this decision, and both can rot in a way a green test
suite would not notice: the drill transcript can stop being what the committed
script prints, and the design note can lose the disclosures that make it honest
(the action-gate gap, the replay exclusion, the orphan window, the backup limit).
These guards make either kind of rot fail here instead.
"""

import pathlib

DOC = pathlib.Path("docs/restore-drills/2026-11-06-served-path-erasure.md")
DESIGN = pathlib.Path("docs/design/content-retention.md")
SCRIPT = pathlib.Path("scripts/drills/phase12_served_path_retention.py")


def _norm(path: pathlib.Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class TestTheTranscriptIsBoundToItsScript:
    def test_the_record_names_the_driver_a_reader_runs(self):
        assert "scripts/drills/phase12_served_path_retention.py" in _norm(DOC)
        assert SCRIPT.exists()

    def test_every_quoted_result_line_is_one_the_script_prints(self):
        doc, script = _norm(DOC), SCRIPT.read_text(encoding="utf-8")
        quoted = [
            "RESULT retention off: /v1/info content_retention =",
            "RESULT retention off: record commitment =",
            "RESULT retention off: erasure request status",
            "RESULT retention store: record commitment =",
            "RESULT retention store: purge status",
            "RESULT retention store: body bytes in the store file after purge =",
            "RESULT split restore: status ok =",
        ]
        for line in quoted:
            assert line in doc, f"the record no longer quotes {line!r}"
            head = line.split(":")[0] + ":"
            assert head in script, f"the script no longer prints {head!r}"

        # The per-check lines print from a label table, so the guard matches the
        # label the script holds rather than a formatted line it never contains.
        for label in (
            "the split restore is reported by name",
            "off mode records none",
            "the pair reconciles clean after the purge",
        ):
            assert label in doc, f"the record no longer reports {label!r}"
            assert f'("{label}"' in script, f"the script dropped the {label!r} check"

    def test_the_record_carries_the_finding_it_was_written_for(self):
        assert "unattested-purge" in _norm(DOC)

    def test_the_driver_asserts_its_preconditions_and_fails_loudly(self):
        """A drill that cannot authenticate must say so, not report a pass on
        nothing: the first run of this one 401'd at its opening request."""
        script = SCRIPT.read_text(encoding="utf-8")
        assert "REFUSED" in script
        assert "AUTH" in script and "create_token" in script
        assert "X-CUSTOS-Retention-Token" in script
        assert "raise SystemExit(main())" in script
        assert "return 0 if not failed else 1" in script


class TestTheDesignNoteKeepsItsDisclosures:
    """Each of these sentences is a limit a reader is entitled to. The note is
    wrong without them, and nothing else in the suite would notice."""

    def test_it_states_both_modes_and_the_default(self):
        doc = _norm(DESIGN)
        assert "CUSTOS_CONTENT_RETENTION=off" in doc
        assert "CUSTOS_CONTENT_RETENTION=store" in doc
        assert "(default)" in doc

    def test_it_states_the_action_gates_retention_status(self):
        """This guard used to require the words "retains nothing", which was the
        gap. Asserting the absence now would pin a defect as the expected state,
        so it requires the endpoint and what it does instead: records through the
        shared path, and says which issue closed the gap."""
        doc = _norm(DESIGN)
        assert "/v1/evaluate_action" in doc
        assert "retention-aware path" in doc
        assert "issue 140" in doc

    def test_it_says_why_replay_is_excluded(self):
        doc = _norm(DESIGN)
        assert "Replay records are excluded on purpose" in doc
        assert "refuses to re-hold" in doc

    def test_it_states_the_orphan_window_and_why_it_is_not_deleted(self):
        doc = _norm(DESIGN)
        assert "body_without_record" in doc
        assert "not deleted automatically" in doc

    def test_it_does_not_claim_a_purge_reaches_a_backup(self):
        assert "does not reach a copy of the store taken before a purge" in _norm(DESIGN)

    def test_it_keeps_verification_and_reconciliation_apart(self):
        doc = _norm(DESIGN)
        assert "still verifies" in doc
        assert "reconcile()" in doc


class TestTheDrillRefusesAConfigurationItCannotMeasure:
    """The pre-purge copy is a file copy of the audit store, which is a property of
    the SQLite backend rather than of a server. The docstring always said so; the
    code did not check, and a run with DATABASE_URL inherited from the shell got
    nine results deep before dying on a missing audit.sqlite. A refusal that names
    the cause is the fix; a traceback that names the symptom is not."""

    def test_a_redirected_audit_store_is_refused_by_name(self):
        import os
        import subprocess
        import sys

        env = dict(os.environ)
        env["DATABASE_URL"] = "postgresql://drill/drill"
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
        )
        assert result.returncode == 2, result.stdout[-800:] + result.stderr[-800:]
        assert "REFUSED: DATABASE_URL is set" in result.stdout
        assert "copies the audit store as a file" in result.stdout
        # A refusal that does not say what would have been wrong is a stop sign
        # without a direction, so it names the property and the drill that does
        # cover this configuration.
        assert "a property of the SQLite backend and not of a server" in result.stdout

    def test_the_refusal_says_where_the_postgres_path_is_measured(self):
        script = SCRIPT.read_text(encoding="utf-8")
        assert "2026-11-06-served-path-postgres.md" in script

    def test_the_backend_that_resolved_is_checked_rather_than_the_variable_alone(self):
        """A second check on the backend the app actually built, because the
        environment variable is one route to PostgreSQL and not the only one."""
        script = SCRIPT.read_text(encoding="utf-8")
        assert "backend_type" in script
        assert '!= "SQLiteBackend"' in script


class TestTheRecordNamesTheBackendItWasMeasuredOn:
    """The retention claims rest on a run whose stores are SQLite, and the deployment
    backend is PostgreSQL. The disclosure is the part a reader needs to weigh the
    claim, so it is pinned like the others: a paragraph that can be deleted without
    a failure is a paragraph that will be."""

    def test_the_design_note_states_which_backend_was_measured(self):
        doc = _norm(DESIGN)
        assert "on the SQLite audit backend" in doc
        assert "has not been run there" in doc

    def test_it_names_the_open_gap_rather_than_implying_coverage(self):
        assert "Issue 149" in _norm(DESIGN)

    def test_the_transcript_names_the_same_gap(self):
        doc = _norm(DOC)
        assert "Both stores in this run are SQLite" in doc
        assert "Issue 149" in doc

    def test_the_design_note_still_says_why_the_argument_from_code_is_insufficient(self):
        doc = _norm(DESIGN)
        assert "cross-tenant loader" in doc
