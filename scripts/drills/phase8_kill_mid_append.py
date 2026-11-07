"""Phase 8: kill the writer mid-append and read what the store holds.

The claim under test is the ordering one: a record is committed to the store
before the caller is told the write succeeded. The injection that can falsify it
is a SIGKILL with no shutdown path, because a graceful stop would let the
process finish whatever it had already promised.

    DATABASE_URL=postgresql://user:pass@host:port/db \
      python3 scripts/drills/phase8_kill_mid_append.py

Reads back through a NEW process, so the verification is not the dead process
agreeing with itself: rows, torn rows (a row missing either hash), and the chain
verification from genesis.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SECONDS = float(os.environ.get("DRILL_SECONDS", "3"))


def _has_table(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.audit_records') IS NOT NULL")
        return bool(cur.fetchone()[0])


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is required: this phase runs the served path against a durable store")
        return 2

    import psycopg2

    baseline_conn = psycopg2.connect(os.environ["DATABASE_URL"])
    with baseline_conn, baseline_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM audit_records") if _has_table(baseline_conn) else None
        rows_before = cur.fetchone()[0] if _has_table(baseline_conn) else 0
    baseline_conn.close()

    env = dict(os.environ)
    env.setdefault("CUSTOS_ENV", "production")
    env.setdefault("CUSTOS_JWT_SECRET", secrets.token_hex(32))

    proc = subprocess.Popen(
        [sys.executable, str(HERE / "writer_loop.py")],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(SECONDS)
    proc.send_signal(signal.SIGKILL)
    out, err = proc.communicate(timeout=30)

    wrote = [int(m) for m in re.findall(r"^wrote (\d+) 200$", out, re.M)]
    reported = len(wrote)
    print(f"reported writes: {reported}")
    print(f"wrote {reported} {200 if wrote else 0}")
    if err.strip():
        print("writer stderr (tail):", err.strip().splitlines()[-1][:160])
    if not wrote:
        print("no acknowledged write landed; rerun with a longer DRILL_SECONDS")
        return 1

    # A new process, not the dead one, reads the store back.
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    with conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM audit_records")
        rows = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM audit_records WHERE record_hash IS NULL"
            " OR previous_hash IS NULL"
        )
        torn = cur.fetchone()[0]
    conn.close()

    sys.path.insert(0, str(ROOT))
    from custos.audit import AuditChain

    chain = AuditChain(database_url=os.environ["DATABASE_URL"])
    ok, why = chain.verify()
    tail = [r.record_hash[:12] for r in chain._records[-2:]]
    durable = rows - rows_before
    print(f"rows in store: {rows} (before this run: {rows_before}, durable from this run: {durable})")
    print(f"torn rows: {torn}")
    print(f"fresh process: PostgreSQLBackend | records: {len(chain._records)} | verify: [{ok}, '{why}']")
    print(f"                last two hashes: {tail}")

    # The result is the direction of the gap, not its size: acknowledged must be
    # a subset of durable, so rows >= acknowledged and no row is torn.
    print(
        "RESULT acknowledged <= durable: "
        f"{reported <= durable} (acknowledged {reported}, durable {durable}, "
        f"at-least-once gap {durable - reported})"
    )
    print(f"RESULT no torn state: {torn == 0}")
    print(f"RESULT fresh process verifies from genesis: {ok}")
    return 0 if (reported <= durable and torn == 0 and ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
