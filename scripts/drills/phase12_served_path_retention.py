"""Phase 12: does the served path keep what it reads, and can it be erased.

Two runs of the same API, differing only in configuration:

  retention off    the gate keeps nothing, every record says ``none``, and an
                   erasure request is refused for having nothing to act on.
  retention store  the body is kept in a per-tenant side store, the record says
                   ``salted-v1``, the erasure endpoint deletes body, salt and
                   commitment and appends an attestation, and the split-restore
                   state is reported by name instead of verifying green in
                   silence.
  action gate      the same erasure rules now reach /v1/evaluate_action: the
                   proposed action is stored, the record names the form, the
                   purge deletes it, and a resubmission is still decided.

Every assertion is a precondition of the claim it supports, and a failed one
reaches the exit code, so this cannot report a pass it did not earn.

Run:  python3 scripts/drills/phase12_served_path_retention.py
SQLite for both stores, so no server is required.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = tempfile.mkdtemp(prefix="drill-retention-")
AUDIT_DB = os.path.join(ROOT, "audit.sqlite")
CONTENT_DIR = os.path.join(ROOT, "content")
TOKEN = "drill-retention-token"
BODY = "patient 6180, 1200 Brickell Bay Dr, dob 1974-09-30"

# Configuration has to be in place before main is imported: the module builds the
# tenant manager at import time, and a store configured after that is exactly the
# anomaly require_durable_audit refuses.
os.environ["AUDIT_DB_PATH"] = AUDIT_DB
os.environ["CUSTOS_ENV"] = "development"
os.environ["CUSTOS_CONTENT_RETENTION"] = "off"
os.environ.pop("CUSTOS_CONTENT_STORE_DIR", None)
os.environ.pop("CUSTOS_RETENTION_ADMIN_TOKEN", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

import main as app_module  # noqa: E402
from custos.auth import create_token  # noqa: E402
from custos.content_retention import reset_store_cache  # noqa: E402
from custos.tenant import TenantManager  # noqa: E402

# Auth is on by default (AUTH_DISABLED unset), so every call that reaches a real
# endpoint carries a bearer token for the same client id it declares. The first
# run of this drill returned 401 at its opening request and reported nothing else,
# which is why the precondition is asserted below rather than assumed.
CLIENT = "drill"
AUTH = {"Authorization": f"Bearer {create_token(CLIENT)}"}


def served_state() -> None:
    """Rebuild module state the way a fresh process would, gate included.

    The action gate keeps the tenant manager it was constructed with, so rebinding
    only ``tenant_manager`` leaves the gate deciding against a manager the app no
    longer serves and writing records to a chain ``/v1/audit`` does not read. This
    drill rebinds between runs to pick up a new AUDIT_DB_PATH, which is exactly
    where that drift would hide.
    """
    manager = TenantManager()
    app_module.tenant_manager = manager
    app_module.action_gate = app_module.ActionGate(manager)


def main() -> int:
    checks = []
    print(f"work directory: {ROOT}")
    if not AUTH.get("Authorization"):
        print("REFUSED: no bearer token could be minted, so nothing here would run")
        return 2

    # -- run 1: retention off -------------------------------------------
    with TestClient(app_module.app) as client:
        info = client.get("/v1/info", headers=AUTH).json()
        print(f"RESULT retention off: /v1/info content_retention = {info['content_retention']}")
        r = client.post("/v1/evaluate", json={"client_id": CLIENT, "content": BODY}, headers=AUTH)
        print(f"RESULT retention off: evaluate status {r.status_code}")
        record = client.get("/v1/audit", headers=AUTH).json()[-1]
        print(
            "RESULT retention off: record commitment = "
            f"{record['commitment']} | binding_version {record['binding_version']}"
        )
        refused = client.post(
            "/v1/retention/purge",
            json={"content_hash": record["content_hash"], "reason": "erasure request"},
            headers={**AUTH, "X-CUSTOS-Retention-Token": TOKEN},
        )
        print(f"RESULT retention off: erasure request status {refused.status_code}")
        print(f"RESULT retention off: erasure refusal names the mode = {'off' in refused.json()['detail']}")
        checks.append(("off mode records none", record["commitment"] == "none"))
        checks.append(("off mode refuses the erasure with a reason", refused.status_code == 503))

    # -- run 2: retention store -----------------------------------------
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.environ["CUSTOS_CONTENT_RETENTION"] = "store"
    os.environ["CUSTOS_CONTENT_STORE_DIR"] = CONTENT_DIR
    os.environ["CUSTOS_RETENTION_ADMIN_TOKEN"] = TOKEN
    reset_store_cache()
    served_state()

    with TestClient(app_module.app) as client:
        info = client.get("/v1/info", headers=AUTH).json()
        print(f"RESULT retention store: /v1/info content_retention = {info['content_retention']}")
        r = client.post("/v1/evaluate", json={"client_id": CLIENT, "content": BODY}, headers=AUTH)
        record = client.get("/v1/audit", headers=AUTH).json()[-1]
        content_hash = record["content_hash"]
        print(f"RESULT retention store: record commitment = {record['commitment']}")
        store_file = os.path.join(CONTENT_DIR, "content-default.sqlite")
        bytes_before_purge = Path(store_file).read_bytes().count(BODY.encode())
        print(f"RESULT retention store: body bytes in the store file = {bytes_before_purge}")

        status = client.get(
            "/v1/retention/status",
            headers={"X-CUSTOS-Retention-Token": TOKEN, **AUTH},
        ).json()
        print(f"RESULT retention store: reconcile before purge ok = {status['ok']}")

        # A copy taken now is a copy BEFORE the attestation exists. Taking it
        # after the purge would restore a chain that already records the erasure,
        # which is not the split state and would report clean for the wrong reason.
        shutil.copy2(AUDIT_DB, os.path.join(ROOT, "audit-pre-purge.sqlite"))

        unauth = client.post(
            "/v1/retention/purge",
            json={"content_hash": content_hash, "reason": "erasure"},
            headers=AUTH,
        )
        print(f"RESULT retention store: purge without the admin token status {unauth.status_code}")

        purge = client.post(
            "/v1/retention/purge",
            json={"content_hash": content_hash, "reason": "customer erasure request"},
            headers={**AUTH, "X-CUSTOS-Retention-Token": TOKEN},
        )
        print(f"RESULT retention store: purge status {purge.status_code} | store_status {purge.json()['store_status']}")
        print(f"RESULT retention store: body bytes in the store file after purge = {Path(store_file).read_bytes().count(BODY.encode())}")
        last_action = client.get("/v1/audit", headers=AUTH).json()[-1]["action"]
        print(f"RESULT retention store: attestation appended = {last_action}")

        after = client.get(
            "/v1/retention/status",
            headers={"X-CUSTOS-Retention-Token": TOKEN, **AUTH},
        ).json()
        print(f"RESULT retention store: reconcile after purge ok = {after['ok']}")

        # The split restore, end to end over HTTP: the chain goes back to before
        # the erasure, the content store stays past it.
        shutil.copy2(os.path.join(ROOT, "audit-pre-purge.sqlite"), AUDIT_DB)
        served_state()
        split = client.get(
            "/v1/retention/status",
            headers={"X-CUSTOS-Retention-Token": TOKEN, **AUTH},
        ).json()
        kinds = [f["kind"] for f in split["findings"]]
        verify = client.get("/v1/audit/verify", headers=AUTH).json()
        print(f"RESULT split restore: /v1/audit/verify = {verify}")
        print(f"RESULT split restore: status ok = {split['ok']} | findings {kinds}")

    checks += [
        ("store mode records the form the store used", record["commitment"] == "salted-v1"),
        ("the body is in the store file", bytes_before_purge == 1),
        ("the pair reconciles clean before the purge", status["ok"] is True),
        ("an unauthenticated erasure is refused", unauth.status_code == 401),
        ("the erasure succeeds", purge.status_code == 200),
        ("the body is gone from the store file", Path(store_file).read_bytes().count(BODY.encode()) == 0),
        ("the attestation is in the chain", last_action == "PURGE"),
        ("the pair reconciles clean after the purge", after["ok"] is True),
        ("the split restore is reported by name", kinds == ["unattested-purge"]),
    ]


    # -- run 3: the action gate, which used to keep nothing ---------------
    gate_audit = os.path.join(ROOT, "audit-gate.sqlite")
    gate_content = os.path.join(ROOT, "content-gate")
    os.makedirs(gate_content, exist_ok=True)
    os.environ["AUDIT_DB_PATH"] = gate_audit
    os.environ["CUSTOS_CONTENT_STORE_DIR"] = gate_content
    reset_store_cache()
    served_state()
    app_module.action_gate.register_tools("default", {"payment_transfer"})
    proposal = {
        "client_id": CLIENT,
        "tool": "payment_transfer",
        "command": "transfer 2500 to acct 9981",
    }

    with TestClient(app_module.app) as client:
        gate_first = client.post("/v1/evaluate_action", json=proposal, headers=AUTH)
        decision = gate_first.json()
        print(f"RESULT action gate: evaluate_action status {gate_first.status_code} | allowed {decision.get('allowed')}")
        gate_record = client.get("/v1/audit", headers=AUTH).json()[-1]
        print(f"RESULT action gate: record commitment = {gate_record['commitment']}")
        gate_store_file = os.path.join(gate_content, "content-default.sqlite")
        # Measured now and kept, not re-read in the checks: the checks run after
        # the purge, so re-reading would compare the post-purge file to a claim
        # about the pre-purge one and pass or fail for the wrong reason.
        gate_bytes_before = Path(gate_store_file).read_bytes().count(
            proposal["command"].encode()
        )
        print(f"RESULT action gate: command bytes in the store file = {gate_bytes_before}")

        gate_status = client.get(
            "/v1/retention/status",
            headers={"X-CUSTOS-Retention-Token": TOKEN, **AUTH},
        ).json()
        print(f"RESULT action gate: reconcile before purge ok = {gate_status['ok']}")

        gate_purge = client.post(
            "/v1/retention/purge",
            json={"content_hash": gate_record["content_hash"], "reason": "erasure request"},
            headers={**AUTH, "X-CUSTOS-Retention-Token": TOKEN},
        )
        print(f"RESULT action gate: purge status {gate_purge.status_code} | store_status {gate_purge.json().get('store_status')}")
        gate_bytes_after = Path(gate_store_file).read_bytes().count(
            proposal["command"].encode()
        )
        print(f"RESULT action gate: command bytes after purge = {gate_bytes_after}")

        gate_after = client.get(
            "/v1/retention/status",
            headers={"X-CUSTOS-Retention-Token": TOKEN, **AUTH},
        ).json()
        print(f"RESULT action gate: reconcile after purge ok = {gate_after['ok']}")

        again = client.post("/v1/evaluate_action", json=proposal, headers=AUTH).json()
        again_record = client.get("/v1/audit", headers=AUTH).json()[-1]
        print(
            "RESULT action gate: after the purge allowed = "
            f"{again['allowed']} | record commitment = {again_record['commitment']}"
        )

    checks += [
        ("the gate allows the registered tool", decision.get("allowed") is True),
        ("the gate record names the form the store used", gate_record["commitment"] == "salted-v1"),
        ("the proposed action is in the store file", gate_bytes_before == 1),
        ("the gate pair reconciles clean before the purge", gate_status["ok"] is True),
        ("the erasure reaches the gate's record", gate_purge.status_code == 200),
        ("the action is gone from the store file", gate_bytes_after == 0),
        ("the gate pair reconciles clean after the purge", gate_after["ok"] is True),
        ("a purged action is still decided", again["allowed"] is True),
        ("the purged action's new record says none", again_record["commitment"] == "none"),
    ]

    for label, passed in checks:
        print(f"RESULT {label}: {passed}")
    failed = [label for label, passed in checks if not passed]
    if failed:
        print(f"FAILED {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
