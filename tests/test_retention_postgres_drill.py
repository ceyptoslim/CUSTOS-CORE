"""The PostgreSQL retention record stays bound to the driver that produced it.

Phase 12's record has guards because its transcript can drift from the script that
prints it. This is the same shape for phase 14, plus one thing phase 12 does not
need: a refusal check, because the obvious way to run this drill is against the
wrong store and a driver that ran anyway would measure nothing.
"""

import os
import pathlib
import subprocess
import sys

DOC = pathlib.Path("docs/restore-drills/2026-11-07-retention-postgres.md")
DRIVER = pathlib.Path("scripts/drills/phase14_retention_postgres.py")
DESIGN = pathlib.Path("docs/design/content-retention.md")
README = pathlib.Path("scripts/drills/README.md")


def _flat(path: pathlib.Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class TestTheRecordIsBoundToItsDriver:
    def test_the_record_names_the_driver_a_reader_runs(self):
        assert "scripts/drills/phase14_retention_postgres.py" in _flat(DOC)
        assert DRIVER.exists()

    def test_every_quoted_result_line_is_one_the_driver_prints(self):
        doc = _flat(DOC)
        source = DRIVER.read_text(encoding="utf-8")
        for phrase in (
            "RESULT scratch database created:",
            "RESULT audit backend =",
            "RESULT record commitment =",
            "RESULT split restore: status ok =",
            "RESULT every check:",
        ):
            assert phrase in doc, f"the record lost {phrase!r}"
            assert phrase.split(":", 1)[0] in source, f"the driver no longer prints {phrase!r}"

    def test_the_record_states_the_limits_of_the_run(self):
        doc = _flat(DOC)
        assert "It is not a pooled cluster" in doc
        assert "one SQLite file per tenant beside the process" in doc


class TestTheDriverRefusesRatherThanMeasuringNothing:
    def test_it_exits_two_and_names_what_is_missing_without_a_database(self):
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        result = subprocess.run(
            [sys.executable, str(DRIVER)], capture_output=True, text=True, env=env, timeout=120
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "REFUSED: DATABASE_URL is required" in result.stdout

    def test_it_refuses_a_url_that_is_not_postgresql(self):
        env = dict(os.environ)
        env["DATABASE_URL"] = "sqlite:///tmp/not-a-server.db"
        result = subprocess.run(
            [sys.executable, str(DRIVER)], capture_output=True, text=True, env=env, timeout=120
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "this drill measures PostgreSQL" in result.stdout

    def test_it_checks_the_backend_that_resolved_rather_than_the_variable(self):
        source = DRIVER.read_text(encoding="utf-8")
        assert '!= "PostgreSQLBackend"' in source
        assert "pg_dump and pg_restore are required" in source


class TestThePackageSaysTheGapIsClosed:
    def test_the_design_note_names_both_runs(self):
        doc = _flat(DESIGN)
        assert "2026-11-07-retention-postgres.md" in doc
        assert "15 checks, all true" in doc

    def test_the_drill_readme_carries_phase_14(self):
        doc = _flat(README)
        assert "phase14_retention_postgres.py" in doc
        assert "Phase 14: retention on PostgreSQL" in doc
