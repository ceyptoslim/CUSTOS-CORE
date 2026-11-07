"""Phase 14: retention on the PostgreSQL audit backend, which phase 12 could not do.

Phase 12 answers the same questions on SQLite, because its split-restore phase takes
its pre-purge copy with a file copy of the audit store, and a server is not a file.
This is the same sequence with the one step that differs replaced: the copy is
`pg_dump` and the restore is a reload into a fresh database.

What it establishes, in order:

  keep     a decision written through /v1/evaluate records `salted-v1` and its body
           is in the content store, with the pair reconciling clean
  erase    the purge removes body, salt and commitment and appends a `purged-v1`
           attestation to the PostgreSQL chain
  split    a chain restored to before the purge, beside a store past it, is reported
           by name as `unattested-purge` instead of verifying green in silence
  replay   the same body submitted after the purge is still decided, records
           `none`, and does not re-hold the bytes

Refusals rather than assumptions: no DATABASE_URL, no psycopg2, no pg_dump or
pg_restore on PATH, a database it cannot create, or a URL that is not PostgreSQL all
exit 2 with a sentence saying which. A drill that runs on the wrong store and reports
green is worse than one that does not run.

Run:  DATABASE_URL=postgresql://user@host/db \\
        python3 scripts/drills/phase14_retention_postgres.py

The database named in DATABASE_URL is never touched. The drill creates its own
`drill_retention_*` database, drops it at the end, and needs CREATEDB.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = tempfile.mkdtemp(prefix="drill-retention-pg-")
CONTENT_DIR = os.path.join(ROOT, "content")
TOKEN = "drill-retention-token"
BODY = "patient 6180, 1200 Brickell Bay Dr, dob 1974-09-30"


def refuse(message: str) -> None:
    print(f"REFUSED: {message}")
    raise SystemExit(2)


def _split_url(url: str):
    """(dsn prefix, database name) for the URI form psycopg2 and pg_dump both take."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if not parts.scheme.startswith("postgres"):
        refuse(f"DATABASE_URL is {parts.scheme!r}, and this drill measures PostgreSQL")
    dbname = parts.path.lstrip("/")
    if not dbname:
        refuse("DATABASE_URL names no database")
    return parts, dbname


def _with_db(url: str, dbname: str) -> str:
    parts, _ = _split_url(url)
    path = f"/{dbname}"
    rebuilt = f"{parts.scheme}://"
    if parts.netloc:
        rebuilt += parts.netloc
    rebuilt += path
    if parts.query:
        rebuilt += f"?{parts.query}"
    return rebuilt


def _admin_connect(url: str):
    import psycopg2

    return psycopg2.connect(_with_db(url, "postgres"))


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        refuse(
            "DATABASE_URL is required. This drill's whole subject is the PostgreSQL "
            "backend, and phase 12 measures the SQLite one."
        )
    _split_url(url)
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        refuse("psycopg2 is not installed, so the drill cannot manage its scratch database")
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        refuse(
            "pg_dump and pg_restore are required: the pre-purge copy of a PostgreSQL "
            "store is a dump, not a file copy. Install postgresql-client or put it on PATH."
        )

    scratch = f"drill_retention_{uuid.uuid4().hex[:8]}"
    dump_file = os.path.join(ROOT, "audit-pre-purge.dump")
    store_dir = os.path.join(CONTENT_DIR, "store")
    os.makedirs(store_dir, exist_ok=True)

    checks: list[tuple[str, bool]] = []
    created = False
    try:
        # -- the scratch database, so the caller's own is never written to ------
        admin = _admin_connect(url)
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{scratch}"')
        admin.close()
        created = True
        print(f"RESULT scratch database created: {scratch}")

        os.environ["DATABASE_URL"] = _with_db(url, scratch)
        os.environ["AUDIT_DB_PATH"] = os.path.join(ROOT, "unused.sqlite")
        os.environ["CUSTOS_ENV"] = "development"
        os.environ["CUSTOS_CONTENT_RETENTION"] = "store"
        os.environ["CUSTOS_CONTENT_STORE_DIR"] = store_dir
        os.environ["CUSTOS_RETENTION_ADMIN_TOKEN"] = TOKEN

        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

        from fastapi.testclient import TestClient  # noqa: E402

        import main as app_module  # noqa: E402
        from custos.auth import create_token  # noqa: E402
        from custos.content_retention import reset_store_cache  # noqa: E402
        from custos.tenant import TenantManager  # noqa: E402

        client_id = "drill"
        auth = {"Authorization": f"Bearer {create_token(client_id)}"}

        def served_state() -> None:
            """Rebuild what the app decides with, after the store underneath changes."""
            manager = TenantManager()
            app_module.tenant_manager = manager
            app_module.action_gate = app_module.ActionGate(manager)
            reset_store_cache()

        served_state()
        drawer = app_module.tenant_manager.get("default")
        backend = drawer.audit_chain.backend_type
        print(f"RESULT audit backend = {backend}")
        if backend != "PostgreSQLBackend":
            refuse(
                f"the audit backend resolved to {backend} rather than PostgreSQLBackend, "
                "so nothing below would be a measurement of a server"
            )

        # -- keep -------------------------------------------------------------
        with TestClient(app_module.app) as client:
            info = client.get("/v1/info", headers=auth).json()
            print(f"RESULT /v1/info content_retention = {info['content_retention']}")
            first = client.post("/v1/evaluate", json={"client_id": client_id, "content": BODY}, headers=auth)
            print(f"RESULT evaluate status {first.status_code}")
            record = client.get("/v1/audit", headers=auth).json()[-1]
            content_hash = record["content_hash"]
            print(f"RESULT record commitment = {record['commitment']} | binding_version {record['binding_version']}")

            store_file = os.path.join(store_dir, "content-default.sqlite")
            body_bytes_before = Path(store_file).read_bytes().count(BODY.encode())
            print(f"RESULT body bytes in the content store = {body_bytes_before}")

            status_before = client.get(
                "/v1/retention/status", headers={"X-CUSTOS-Retention-Token": TOKEN, **auth}
            ).json()
            print(f"RESULT reconcile before purge ok = {status_before['ok']}")

            # -- the copy, which is the step that differs from phase 12 ---------
            dumped = _run([pg_dump, "-Fc", "-f", dump_file, _with_db(url, scratch)])
            print(f"RESULT pg_dump exit {dumped.returncode} | bytes {os.path.getsize(dump_file) if os.path.exists(dump_file) else 0}")
            if dumped.returncode != 0:
                print(dumped.stderr[-500:])

            # -- erase --------------------------------------------------------
            unauth = client.post(
                "/v1/retention/purge",
                json={"content_hash": content_hash, "reason": "erasure"},
                headers=auth,
            )
            print(f"RESULT purge without the admin token status {unauth.status_code}")

            purge = client.post(
                "/v1/retention/purge",
                json={"content_hash": content_hash, "reason": "customer erasure request"},
                headers={**auth, "X-CUSTOS-Retention-Token": TOKEN},
            )
            print(f"RESULT purge status {purge.status_code} | store_status {purge.json().get('store_status')}")
            body_bytes_after = Path(store_file).read_bytes().count(BODY.encode())
            print(f"RESULT body bytes in the content store after purge = {body_bytes_after}")
            last_action = client.get("/v1/audit", headers=auth).json()[-1]["action"]
            print(f"RESULT attestation appended = {last_action}")

            status_after = client.get(
                "/v1/retention/status", headers={"X-CUSTOS-Retention-Token": TOKEN, **auth}
            ).json()
            print(f"RESULT reconcile after purge ok = {status_after['ok']}")

        # -- split: restore the chain to before the purge, keep the store past it
        admin = _admin_connect(url)
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{scratch}"')
        admin.close()
        restored = _run([pg_restore, "-d", _with_db(url, scratch), "--no-owner", dump_file])
        print(f"RESULT pg_restore exit {restored.returncode}")
        if restored.returncode != 0:
            print(restored.stderr[-500:])

        served_state()
        with TestClient(app_module.app) as client:
            split = client.get(
                "/v1/retention/status", headers={"X-CUSTOS-Retention-Token": TOKEN, **auth}
            ).json()
            kinds = [f["kind"] for f in split["findings"]]
            verify = client.get("/v1/audit/verify", headers=auth).json()
            print(f"RESULT split restore: /v1/audit/verify = {verify}")
            print(f"RESULT split restore: status ok = {split['ok']} | findings {kinds}")

            # -- replay: an erasure must not become a blacklist -----------------
            again = client.post("/v1/evaluate", json={"client_id": client_id, "content": BODY}, headers=auth)
            print(f"RESULT resubmitting purged content status {again.status_code}")
            replay_record = client.get("/v1/audit", headers=auth).json()[-1]
            print(f"RESULT resubmission commitment = {replay_record['commitment']}")
            body_bytes_replay = Path(store_file).read_bytes().count(BODY.encode())
            print(f"RESULT body bytes after resubmission = {body_bytes_replay}")

        checks += [
            ("the decision is recorded on the PostgreSQL chain", first.status_code == 200),
            ("the record names the form the store used", record["commitment"] == "salted-v1"),
            ("the body is in the content store", body_bytes_before == 1),
            ("the pair reconciles clean before the purge", status_before["ok"] is True),
            ("the pre-purge copy is a dump that exists", os.path.getsize(dump_file) > 0),
            ("an unauthenticated erasure is refused", unauth.status_code == 401),
            ("the erasure succeeds", purge.status_code == 200),
            ("the body is gone from the store", body_bytes_after == 0),
            ("the attestation is in the PostgreSQL chain", last_action == "PURGE"),
            ("the pair reconciles clean after the purge", status_after["ok"] is True),
            ("the restored chain verifies on its own terms", verify["valid"] is True),
            ("the split restore is reported by name", kinds == ["unattested-purge"]),
            ("a purged body is still decided", again.status_code == 200),
            ("its new record says none", replay_record["commitment"] == "none"),
            ("it does not re-hold the bytes", body_bytes_replay == 0),
        ]
    finally:
        if created:
            try:
                admin = _admin_connect(url)
                admin.autocommit = True
                with admin.cursor() as cur:
                    cur.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
                admin.close()
                print(f"RESULT scratch database dropped: {scratch}")
            except Exception as exc:  # noqa: BLE001
                print(f"RESULT scratch database could not be dropped: {str(exc)[:120]}")

    for label, passed in checks:
        print(f"RESULT {label}: {passed}")
    failed = [label for label, passed in checks if not passed]
    if failed:
        print(f"FAILED {failed}")
        return 1
    print(f"RESULT every check: {len(checks)} of {len(checks)} true on PostgreSQL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
