"""Phase 9: the store fills mid-append, on the served path (SQLite).

SQLite here rather than PostgreSQL because the shim injects the errno per file
and a single file is the simplest target. The fullness is injected, not produced:
see enospc.c beside this file, which is why the device does not need to be full.

    gcc -shared -fPIC -O2 -o /tmp/enospc.so scripts/drills/enospc.c -ldl
    DRILL_DB=/tmp/drill-full/audit.sqlite \\
      ENOSPC_AFTER=72000 ENOSPC_TARGET=audit.sqlite LD_PRELOAD=/tmp/enospc.so \\
      python3 scripts/drills/phase9_disk_full.py

The property under test: the in-memory chain never advances past what the store
accepted. A record the service believes in and the store does not hold would be
an authorization nobody can audit, which is the failure this gate exists to
prevent, and a full disk is the cheapest way to try to produce one.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import os
import secrets
import sys
import time
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import main  # noqa: E402

secret = os.environ.setdefault("CUSTOS_JWT_SECRET", secrets.token_hex(32))


def token(name: str) -> dict:
    return {
        "Authorization": "Bearer "
        + jwt.encode({"sub": name, "exp": int(time.time()) + 3600}, secret, algorithm="HS256")
    }


def call(client, name: str, content: str):
    return client.post(
        "/v1/evaluate",
        json={"client_id": name, "content": content},
        headers=token(name),
    )


def main_run() -> int:
    chain = main.tenant_manager.get("default").audit_chain
    backend = type(chain._backend).__name__
    print(f"RESULT audit backend: {backend}")
    if backend == "InMemoryBackend":
        # A dev process defaults to memory, where the injection has nothing to
        # fill and the run would report a clean pass while measuring nothing.
        print(
            "refusing to run: the served path is on InMemoryBackend, so there is no "
            "store to fill. Set CUSTOS_ENV=production and AUDIT_DB_PATH, which is "
            "what selects the SQLite backend."
        )
        return 2
    with TestClient(main.app, raise_server_exceptions=True) as client:
        accepted = 0
        failure = None
        for i in range(1, 40):
            try:
                call(client, f"full-{i}", f"record {i}")
                accepted += 1
            except Exception as exc:  # noqa: BLE001 - the failure is the result
                failure = (i, type(exc).__name__, str(exc)[:120])
                break
        print("RESULT accepted before the store filled:", accepted)
        print("RESULT failure:", failure)
        print("RESULT in-process chain length at failure:", len(chain._records))
        try:
            call(client, "after", "after")
            print("RESULT next request: accepted (unexpected)")
        except Exception as exc:  # noqa: BLE001
            print(f"RESULT next request: still refused, {type(exc).__name__}: {str(exc)[:80]}")
        in_memory = len(chain._records)

    # The store as it stands, read without the shim in play (this process is not
    # the process that failed, so the shim's byte counter is not the question).
    db = os.environ.get("AUDIT_DB_PATH") or os.environ.get("DRILL_DB")
    if db and Path(db).exists():
        import sqlite3

        with sqlite3.connect(db) as conn:
            rows = conn.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0]
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            clients = [
                r[0] for r in conn.execute("SELECT DISTINCT client_id FROM audit_records").fetchall()
            ]
        print(f"rows: {rows}")
        print(f"integrity_check: {check}")
        print(f"client ids: {clients}")
        print(
            "RESULT in-memory never ahead of the store: "
            f"{in_memory <= rows} (memory {in_memory}, store {rows})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main_run())
