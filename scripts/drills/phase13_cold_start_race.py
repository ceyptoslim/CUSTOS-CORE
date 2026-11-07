"""Phase 13: two cold starts on an empty store, at the same instant.

Issue 131 was found by accident: phase 10's first attempt against a database with
no schema had one process die inside schema creation with

    psycopg2.errors.UniqueViolation: duplicate key value violates unique
    constraint "pg_type_typname_nsp_index"

which is upstream of the chain and before the fork guard is reached. The fix is
an advisory lock taken before any schema change, so the second process waits
instead of colliding.

This phase measures the defect itself rather than the fork condition, so it does
the opposite of phase 10: no warm-up, no stagger, an empty schema every trial.

    DATABASE_URL=postgresql://user:pass@host:port/db \\
      python3 scripts/drills/phase13_cold_start_race.py

The scratch schemas are created and dropped by this driver, so DATABASE_URL may
point at any database the runner can create schemas in. Nothing outside those
schemas is touched.

Pass condition, per trial: BOTH processes reach `schema up`, exactly one append
lands, and the other is refused at the store with ChainForkError.

This needs a real PostgreSQL server. A fake store cannot contain the defect,
because the duplicate-key error is raised by the PostgreSQL catalogs and not by
any code in this repository. Phase 10's warm-up exists for the same reason and
stays: it isolates the fork condition from this one.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WORKERS = ("A", "B")
TRIALS = int(os.environ.get("CUSTOS_DRILL_TRIALS", "5"))
LEAD_SECONDS = 1.5


def with_schema(url: str, schema: str) -> str:
    """The same database, with search_path pinned to one scratch schema."""
    option = quote(f"-csearch_path={schema}", safe="")
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}options={option}"


def spawn(name: str, url: str, start_at: float, log: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(HERE / "phase13_cold_start_worker.py"), name],
        cwd=str(ROOT),
        env={
            **os.environ,
            "CUSTOS_DRILL_URL": url,
            "CUSTOS_DRILL_START_AT": f"{start_at:.6f}",
        },
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        text=True,
    )


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("REFUSED: DATABASE_URL is required. The defect lives in the database catalogs,")
        print("so a fake or in-memory store cannot contain it and this would measure nothing.")
        return 2

    try:
        import psycopg2
    except ImportError:
        print("REFUSED: psycopg2 is not installed, so the scratch schemas cannot be managed")
        return 2

    try:
        conn = psycopg2.connect(url)
    except Exception as exc:  # noqa: BLE001
        print(f"REFUSED: cannot reach the server: {str(exc).splitlines()[0][:160]}")
        return 2

    conn.autocommit = True
    checks = []
    print(f"server: {conn.get_dsn_parameters().get('host', '?')} | trials: {TRIALS}")

    # Not `with conn:` -- that opens a transaction block, and a schema created
    # inside it is invisible to the workers until the block exits, which is the
    # whole race this phase is trying to stage. autocommit is set above and every
    # statement is committed as it runs.
    with tempfile.TemporaryDirectory(prefix="drill-coldstart-") as tmp:
        for trial in range(1, TRIALS + 1):
            schema = f"drill_cold_{secrets.token_hex(4)}"
            with conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA {schema}")
            trial_url = with_schema(url, schema)
            start_at = time.time() + LEAD_SECONDS
            logs = {name: Path(tmp) / f"trial{trial}-{name}.txt" for name in WORKERS}
            procs = {name: spawn(name, trial_url, start_at, logs[name]) for name in WORKERS}
            for proc in procs.values():
                proc.wait(timeout=90)

            text = {name: logs[name].read_text() for name in WORKERS}
            schemas_up = sum("schema up" in body for body in text.values())
            allowed = sum("append allowed" in body for body in text.values())
            refused = sum("append refused ChainForkError" in body for body in text.values())
            deaths = [line for body in text.values() for line in body.splitlines() if "SCHEMA died" in line]

            print(
                f"RESULT trial {trial}: schema up {schemas_up}/2 | "
                f"appends allowed {allowed} | refused with ChainForkError {refused}"
            )
            for line in deaths:
                print(f"RESULT trial {trial}: {line.split(': ', 1)[-1]}")
            if deaths or schemas_up != 2:
                # The worker's own words, because a count alone does not say why.
                for name in WORKERS:
                    for line in text[name].splitlines()[:4]:
                        print(f"  {name}: {line}")

            checks += [
                (f"trial {trial}: both cold starts reached schema creation", schemas_up == 2),
                (f"trial {trial}: exactly one writer appended", allowed == 1),
                (f"trial {trial}: the other was refused at the store", refused == 1),
            ]

            with conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA {schema} CASCADE")

    for label, passed in checks:
        print(f"RESULT {label}: {passed}")
    failed = [label for label, passed in checks if not passed]
    if failed:
        print(f"FAILED {failed}")
        return 1
    print(f"RESULT every trial: {len(checks)} checks, both processes up, one append each")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
