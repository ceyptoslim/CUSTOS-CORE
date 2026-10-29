#!/usr/bin/env python3
"""
custody_attack.py — executes the pre-registered custody attack class.

Part B of docs/red-proof-records/sabotage-custody/DESIGN.md (hash pinned in
.github/workflows/ci-red-proof.yml). Each attack builds a real deployment
shape — SQLite-backed audit chain, GitAnchorSink on a real git repository —
applies the attack, and enforces the pre-registered expected verdict.
Exit code is non-zero if ANY expected verdict does not occur (faulty-green
for the custody mechanism: the anchors failed to catch what the internal
chain cannot).

Attacks (pre-registered):
  001-rewrite-backend  mutate the SQLite store in place and recompute the
                       whole chain consistently — internal verify() must
                       stay GREEN, external custody verify must report
                       CONTRADICTION (P2, rewrite detected).
  002-truncate-tail    delete the newest K records directly in SQLite —
                       internal verify() GREEN, external P4 CONTRADICTION
                       (length discontinuity).
  003-suppress-anchor  destroy the sink mid-operation — gap must be
                       recorded and carried in-band by the next successful
                       anchor, enforcement must continue unaffected
                       (fail-visible, not fail-blocking).

Writes a v3-compatible evidence record to stdout.
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from custos.audit import AuditChain, compute_record_hash
from custos.custody import (
    AnchorManager,
    GitAnchorSink,
    verify_custody,
    ESTABLISHED,
    CONTRADICTION,
)

N_RECORDS = 12
ATTACK_INDEX = 4  # mid-chain record rewritten by 001
TRUNCATE_K = 4     # newest records deleted by 002


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _record_hash_fields(row: dict, previous_hash: str) -> str:
    """Rehash a row with the emitter's own preimage.

    The attacker has to be at least as strong as the verifier, or this attack
    measures nothing. This used to implement the original six-field preimage
    locally and silently went stale when the preimage grew (policy citation,
    tenant binding, trace binding): the "consistent rewrite" then failed
    INTERNAL verification instead of passing it, which inverted the
    pre-registered expectation and turned a passing attack into FAULTY-GREEN.

    Delegating to the canonical definition means a future preimage change
    strengthens the attacker automatically. Run 40936323689 (2026-10-29)
    caught this; see docs/red-proof-records/custody-attack-staleness.md.
    """
    return compute_record_hash(row, previous_hash)


def _build_deployment(tmp: str):
    """Real deployment shape: SQLite chain + git-anchored custody."""
    repo = os.path.join(tmp, "anchor-repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@invalid",
         "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=repo, check=True,
    )
    sink = GitAnchorSink(repo)
    db_path = os.path.join(tmp, "audit.db")
    chain = AuditChain(db_path=db_path)
    for i in range(N_RECORDS):
        chain.record(
            client_id="default",
            action="allow" if i % 2 == 0 else "deny",
            reason=f"decision {i}",
            content=f"content {i}",
        )
    manager = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
    manager.anchor_due()
    assert len(sink.load_anchors()) == 1, "baseline anchor must land"
    return chain, sink, manager, db_path, repo


def _rows(conn: sqlite3.Connection):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(
        "SELECT * FROM audit_records ORDER BY id")]


def attack_rewrite_backend(tmp: str) -> dict:
    """custody-attack-001: rewrite the store consistently; internal verify
    stays green; external anchors report CONTRADICTION."""
    chain, sink, _m, db_path, repo = _build_deployment(tmp)

    # --- the attack: rewrite mid-chain reason, recompute every later hash
    conn = sqlite3.connect(db_path)
    rows = _rows(conn)
    tampered_at = rows[ATTACK_INDEX]["id"]
    conn.execute(
        "UPDATE audit_records SET reason = ? WHERE id = ?",
        ("tampered: attacker reason", tampered_at),
    )
    conn.commit()
    rows = _rows(conn)
    prev = rows[ATTACK_INDEX - 1]["record_hash"]
    for row in rows[ATTACK_INDEX:]:
        new_hash = _record_hash_fields(row, prev)
        conn.execute(
            "UPDATE audit_records SET previous_hash = ?, record_hash = ? WHERE id = ?",
            (prev, new_hash, row["id"]),
        )
        conn.commit()
        prev = new_hash
    conn.close()

    # --- reload from the tampered store (what an auditor sees)
    reloaded = AuditChain(db_path=db_path)
    internal_ok, internal_msg = reloaded.verify()
    result = verify_custody(reloaded.get_records(), sink.load_anchors())

    expected = {
        "internal_verify": True,
        "P2_anchored_heads_match_store": CONTRADICTION,
        "overall": CONTRADICTION,
    }
    actual = {
        "internal_verify": internal_ok,
        "P2_anchored_heads_match_store": result["verdicts"]["P2_anchored_heads_match_store"],
        "overall": result["overall"],
    }
    return {
        "attack": "custody-attack-001-rewrite-backend",
        "expected": expected,
        "actual": actual,
        "observations": {
            "internal_verify_message": internal_msg,
            "tampered_row_id": tampered_at,
            "external_detail": result["detail"].get("p2_break"),
            "external_verdicts": result["verdicts"],
            "anchor_repo": repo,
        },
        "detected": actual == expected,
    }


def attack_truncate_tail(tmp: str) -> dict:
    """custody-attack-002: delete the newest K records; internal verify
    stays green; external P4 reports the length discontinuity."""
    chain, sink, _m, db_path, repo = _build_deployment(tmp)

    conn = sqlite3.connect(db_path)
    rows = _rows(conn)
    survivor = rows[-(TRUNCATE_K + 1)]["id"]
    conn.execute("DELETE FROM audit_records WHERE id > ?", (survivor,))
    conn.commit()
    conn.close()

    reloaded = AuditChain(db_path=db_path)
    internal_ok, internal_msg = reloaded.verify()
    result = verify_custody(reloaded.get_records(), sink.load_anchors())

    expected = {
        "internal_verify": True,
        "P4_store_completeness": CONTRADICTION,
        "overall": CONTRADICTION,
    }
    actual = {
        "internal_verify": internal_ok,
        "P4_store_completeness": result["verdicts"]["P4_store_completeness"],
        "overall": result["overall"],
    }
    return {
        "attack": "custody-attack-002-truncate-tail",
        "expected": expected,
        "actual": actual,
        "observations": {
            "internal_verify_message": internal_msg,
            "records_surviving": N_RECORDS - TRUNCATE_K,
            "records_anchored": N_RECORDS,
            "external_detail": result["detail"].get("p4_break"),
            "external_verdicts": result["verdicts"],
            "anchor_repo": repo,
        },
        "detected": actual == expected,
    }


def attack_suppress_anchor(tmp: str) -> dict:
    """custody-attack-003: destroy the sink mid-operation; the gap must be
    recorded, enforcement must continue, the next successful anchor must
    carry the gap in-band. Fail-visible, not fail-blocking."""
    chain, sink, manager, db_path, repo = _build_deployment(tmp)

    # drive new records past the anchor threshold
    for i in range(N_RECORDS, N_RECORDS + 2):
        chain.record(
            client_id="default", action="deny",
            reason=f"post-outage {i}", content=f"content {i}",
        )

    # --- the attack: destroy the sink repository mid-operation
    shutil.rmtree(repo)

    # enforcement must continue unaffected while the sink is down
    enforcement_ok = True
    try:
        for i in range(N_RECORDS + 2, N_RECORDS + 4):
            chain.record(
                client_id="default", action="allow",
                reason=f"during-outage {i}", content=f"content {i}",
            )
        manager.anchor_due()
    except Exception as exc:  # pragma: no cover — the failure mode itself
        enforcement_ok = False
        err = str(exc)
    else:
        err = None

    # fail-visible state must surface the outage
    health_during = manager.health()
    gap_recorded = any(
        t.get("pending_gap") for t in health_during["tenants"].values()
    )

    # --- recovery: sink returns; the next anchor carries the gap in-band.
    # (The failed append may have left a partial write behind — the write
    # path is not atomic; the git COMMIT is the landing that matters.
    # The re-initialized repo needs its identity config restored.)
    shutil.rmtree(repo, ignore_errors=True)
    os.makedirs(repo, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "custos-custody"],
                   cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "custody@custos.invalid"],
                   cwd=repo, check=True, capture_output=True)
    manager.anchor_due()
    anchors_after = sink.load_anchors()
    gap_carried = any(a.get("gap") for a in anchors_after)
    health_after = manager.health()
    gap_cleared = not any(
        t.get("pending_gap") for t in health_after["tenants"].values()
    )

    expected = {
        "enforcement_unaffected": True,
        "gap_recorded_while_down": True,
        "gap_carried_in_band_by_next_anchor": True,
        "gap_cleared_after_recovery": True,
    }
    actual = {
        "enforcement_unaffected": enforcement_ok,
        "gap_recorded_while_down": gap_recorded,
        "gap_carried_in_band_by_next_anchor": gap_carried,
        "gap_cleared_after_recovery": gap_cleared,
    }
    return {
        "attack": "custody-attack-003-suppress-anchor",
        "expected": expected,
        "actual": actual,
        "observations": {
            "enforcement_error": err,
            "health_during_outage": health_during,
            "anchors_after_recovery": len(anchors_after),
            "gap_object": (anchors_after[-1].get("gap") if anchors_after else None),
            "anchor_repo": repo,
        },
        "detected": actual == expected,
    }


ATTACKS = {
    "001-rewrite-backend": attack_rewrite_backend,
    "002-truncate-tail": attack_truncate_tail,
    "003-suppress-anchor": attack_suppress_anchor,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("attack", choices=sorted(ATTACKS.keys()))
    args = parser.parse_args()

    run_id = os.getenv("GITHUB_RUN_ID", "local")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    ).stdout.strip() or "unknown"

    tmp = tempfile.mkdtemp(prefix="custody-attack-")
    try:
        result = ATTACKS[args.attack](tmp)
        script_path = os.path.abspath(__file__)
        record = {
            "record_version": 3,
            "identity": {
                "run_id": run_id,
                "attack_id": args.attack,
                "commit_sha": commit,
                "attack_script_sha256": hashlib.sha256(
                    open(script_path, "rb").read()
                ).hexdigest(),
                "pre_registered_design": "docs/red-proof-records/sabotage-custody/DESIGN.md",
            },
            "time": {
                "executed_at_utc": _utc_now(),
            },
            "observations": result["observations"],
            "verdict": {
                "expected": result["expected"],
                "actual": result["actual"],
                "verdict": "DETECTED" if result["detected"] else "FAULTY-GREEN",
                "rule": {
                    "id": "custody-attack-verdict-rule",
                    "version": 1,
                    "mapping": "actual == expected -> DETECTED; else FAULTY-GREEN",
                },
            },
            "provenance": {
                "workflow": "ci-red-proof (custody-attacks)",
                "repo": "ceyptoslim/CUSTOS-CORE",
                "runner": os.getenv("GITHUB_ACTIONS", "local") or "local",
            },
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    json.dump(record, sys.stdout, indent=2, default=str)
    print()
    if not result["detected"]:
        print(
            f"::error::FAULTY-GREEN — attack {args.attack} produced actual "
            f"verdicts that do not match the pre-registered expectations. "
            "The custody mechanism failed to detect this attack class.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
