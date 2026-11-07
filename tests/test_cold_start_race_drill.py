"""The cold-start race record stays bound to the driver that produced it.

Two claims are being held here, and they are different claims.

The first is the fix: two processes released at the same instant against an empty
database both reach the end of schema creation. That is measured by
`scripts/drills/phase13_cold_start_race.py` and not by the modelled unit test in
`tests/test_store_refusals.py`, because the duplicate-key error comes from the
PostgreSQL catalogs and no fake store raises it.

The second is the shape of the record: the numbers quoted in the design note and in
the drill README are the trials the committed driver ran, on the commits they name,
with the failure mode it reported on the build before the lock. A record whose
quoted lines are not lines the script prints ages into a claim nobody can re-run,
which is the defect these guards exist for.

Nothing here needs a server. The refusal path is what runs in CI; the measurement
itself is re-run by hand, and a suite that skipped without a database would leave
this unguarded exactly where it matters.
"""

import pathlib
import subprocess
import sys

DRIVER = pathlib.Path("scripts/drills/phase13_cold_start_race.py")
WORKER = pathlib.Path("scripts/drills/phase13_cold_start_worker.py")
DESIGN_NOTE = pathlib.Path("docs/design/store-refusals-and-cold-start.md")
DRILLS_README = pathlib.Path("scripts/drills/README.md")
CONSTRAINT_DOC = pathlib.Path("docs/design/single-replica-constraint.md")

FIXED_COMMIT = "40d6519"
BEFORE_LOCK = "58c7462"


def _flat(path: pathlib.Path) -> str:
    """Whitespace-normalised: prose wraps mid-phrase, so matching raw lines would
    fail on layout rather than on content."""
    return " ".join(path.read_text(encoding="utf-8").split())


class TestTheDriverExistsAndCanBeRead:
    def test_both_halves_of_the_driver_are_committed(self):
        assert DRIVER.exists(), "the driver the record names must be in the repository"
        assert WORKER.exists(), "the driver cannot stage two processes without its worker"

    def test_the_driver_compiles_without_a_server(self):
        for path in (DRIVER, WORKER):
            source = path.read_text(encoding="utf-8")
            assert compile(source, str(path), "exec") is not None, path


class TestTheDriverRefusesRatherThanMeasuringNothing:
    def test_it_exits_two_and_says_why_when_no_database_is_given(self):
        import os

        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        result = subprocess.run(
            [sys.executable, str(DRIVER)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "REFUSED" in result.stdout

    def test_the_refusal_names_why_a_fake_store_would_not_do(self):
        flat = _flat(DRIVER)
        assert "cannot contain it" in flat or "cannot contain the defect" in flat

    def test_the_scratch_schema_is_committed_before_the_workers_start(self):
        """The bug this guard exists for: `with conn:` opens a transaction block, so
        a schema created inside it is invisible to the workers and every trial dies
        at connect. That reads as the defect still present, which is a false failure
        in the direction that matters least, but the same mistake inside the pass
        condition would be a false pass."""
        source = DRIVER.read_text(encoding="utf-8")
        assert "conn.autocommit = True" in source
        assert "with conn," not in source, "a transaction block hides the scratch schema"


class TestTheRecordQuotesWhatTheDriverPrints:
    def test_the_design_note_names_the_driver_and_both_commits(self):
        flat = _flat(DESIGN_NOTE)
        assert "scripts/drills/phase13_cold_start_race.py" in flat
        assert FIXED_COMMIT in flat
        assert BEFORE_LOCK in flat

    def test_the_design_note_quotes_the_per_trial_line_the_driver_prints(self):
        flat = _flat(DESIGN_NOTE)
        assert "schema up 2/2 | appends allowed 1 | refused with ChainForkError 1" in flat
        source = DRIVER.read_text(encoding="utf-8")
        assert "schema up {schemas_up}/2" in source
        assert "refused with ChainForkError {refused}" in source

    def test_the_design_note_quotes_the_failure_the_old_build_produced(self):
        flat = _flat(DESIGN_NOTE)
        assert "pg_type_typname_nsp_index" in flat
        assert "UniqueViolation" in flat

    def test_the_drill_readme_carries_the_same_measurement(self):
        flat = _flat(DRILLS_README)
        assert "phase13_cold_start_race.py" in flat
        assert "5/5" in flat
        assert FIXED_COMMIT in flat

    def test_the_design_note_no_longer_says_the_race_was_only_modelled(self):
        """The sentence that was true until the real-cluster run existed. Keeping it
        would understate the evidence in the one document a reader checks."""
        flat = _flat(DESIGN_NOTE)
        assert "It does not measure a real PostgreSQL cluster" not in flat
        assert "not of a rolling replacement in a cluster" in flat


class TestTheConstraintDocStopsCallingItAnOpenDefect:
    def test_it_records_the_race_as_fixed_with_its_mechanism(self):
        flat = _flat(CONSTRAINT_DOC)
        assert "pg_advisory_xact_lock" in flat
        assert "fixed" in flat
        assert "phase13_cold_start_race.py" in flat

    def test_it_still_states_what_the_check_cannot_detect(self):
        """The correction must not quietly upgrade the check: it still cannot see a
        rollout overlap, and that limit is the reason the doc exists."""
        flat = _flat(CONSTRAINT_DOC)
        assert "cannot detect how many processes are running" in flat
        assert "operator fact" in flat
