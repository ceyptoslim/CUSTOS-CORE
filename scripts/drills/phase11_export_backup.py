"""Phase 11: export and backup, and the negative result a restore produces.

The question this answers is not "does a backup work". It is "what does a
backup taken before an erasure do to that erasure", and the answer is that it
undoes it silently: the restored store verifies green, the body is readable
again, and nothing in the restored chain says a purge ever happened.

Three stores are involved and they do not share a recovery window:

  content body   in the content store, deleted by purge
  salt + commitment  in the same row of the content store, so the same file
                 copy recovers body and salt together
  purge attestation  in the audit store, appended after the deletion

Run:  python3 scripts/drills/phase11_export_backup.py
No server required. Both stores are SQLite files, so a backup is a file copy
and a reader can reproduce every line of the transcript.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custos.audit import COMMITMENT_NONE, AuditChain  # noqa: E402
from custos.retention import ContentStore  # noqa: E402

BODIES = {
    "c1": "patient 4471, 118 Palm Ave, dob 1979-02-11",
    "c2": "patient 9022, 40 Ocean Dr, dob 1968-07-03",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count_occurrences(path: Path, needle: str) -> int:
    """Raw byte search, not a query through the store.

    A row deleted by the store is gone from the query view whether or not its
    bytes are still in the file, and the question here is about the file.
    """
    return path.read_bytes().count(needle.encode("utf-8"))


def backup(label: str, audit_db: Path, content_db: Path, into: Path) -> dict:
    target = into / label
    target.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, src in (("audit", audit_db), ("content", content_db)):
        dst = target / src.name
        shutil.copy2(src, dst)
        out[name] = {
            "path": dst.relative_to(into).as_posix(),
            "bytes": dst.stat().st_size,
            "sha256": sha256_file(dst),
        }
    return out


def export_chain(chain: AuditChain, content: ContentStore) -> list[dict]:
    """What an export carries: the record side, and the store's inventory.

    No bodies and no salts. An export that carried either would be a second
    copy of the data a purge exists to remove, so the export is deliberately the
    weaker artifact: it says which digests exist and what form they hold.
    """
    rows = []
    for index, rec in enumerate(chain._records):
        rows.append(
            {
                "kind": "record",
                "index": index,
                "action": rec.action,
                "commitment": rec.commitment,
                "record_hash": rec.record_hash,
                "previous_hash": rec.previous_hash,
            }
        )
    for content_hash in (hashlib.sha256(b.encode()).hexdigest() for b in BODIES.values()):
        rows.append(
            {
                "kind": "content",
                "content_hash": content_hash,
                "status": content.status(content_hash),
                "marker": content.marker(content_hash),
            }
        )
    return rows


def write_export(rows: list[dict], path: Path) -> None:
    path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="drill-export-"))
    audit_db = root / "audit.sqlite"
    content_db = root / "content.sqlite"
    print(f"work directory: {root}")

    chain = AuditChain(db_path=str(audit_db))
    content = ContentStore(str(content_db))

    # -- live state before the backup -----------------------------------
    h1 = content.put_and_record(
        BODIES["c1"],
        chain=chain,
        client_id="drill",
        action="ALLOW",
        reason="phase 11 record one",
    ).content_hash
    h2 = content.put_and_record(
        BODIES["c2"],
        chain=chain,
        client_id="drill",
        action="ALLOW",
        reason="phase 11 record two",
    ).content_hash
    # A decision with no content, which is what the served path writes today.
    chain.record(
        client_id="drill",
        action="DENY",
        reason="phase 11 record three, no content bound",
        content="",
    )
    print(f"RESULT records before backup: {len(chain._records)} | verify: {chain.verify()}")
    print(f"RESULT content status: c1={content.status(h1)} c2={content.status(h2)}")

    # -- backup 1: taken before the erasure -----------------------------
    b1 = backup("backup-1-pre-purge", audit_db, content_db, root)
    print(f"RESULT backup-1 audit: {b1['audit']['bytes']} bytes sha256 {b1['audit']['sha256'][:16]}")
    print(f"RESULT backup-1 content: {b1['content']['bytes']} bytes sha256 {b1['content']['sha256'][:16]}")

    # -- the erasure ----------------------------------------------------
    attestation = content.purge(h1, chain=chain, client_id="ops", reason="erasure request")
    print(f"RESULT purge attestation: {attestation[:16]} | records: {len(chain._records)}")
    print(f"RESULT live c1 status after purge: {content.status(h1)}")
    print(f"RESULT live verify after purge: {chain.verify()}")
    live_hits = count_occurrences(content_db, BODIES["c1"])
    print(f"RESULT body bytes left in the live content store: {live_hits}")

    # The deletion has to hold in the store itself, not in its query view.
    try:
        content.open_body(h1)
        print("RESULT live body readable after purge: True (unexpected)")
        ok_live = False
    except Exception as exc:  # noqa: BLE001 - the type is what is being reported
        print(f"RESULT live body readable after purge: False ({type(exc).__name__})")
        ok_live = live_hits == 0

    # -- backup 2: taken after the erasure ------------------------------
    b2 = backup("backup-2-post-purge", audit_db, content_db, root)
    b2_hits = count_occurrences(root / b2["content"]["path"], BODIES["c1"])
    print(f"RESULT backup-2 content: {b2['content']['bytes']} bytes sha256 {b2['content']['sha256'][:16]}")
    print(f"RESULT body bytes inside backup-2: {b2_hits}")

    # -- the export -----------------------------------------------------
    live_export = root / "export-live.jsonl"
    write_export(export_chain(chain, content), live_export)
    export_text = live_export.read_text()
    body_in_export = sum(export_text.count(b) for b in BODIES.values())
    forms = sorted({r["commitment"] for r in map(json.loads, export_text.splitlines()) if r["kind"] == "record"})
    print(f"RESULT live export: {len(export_text.splitlines())} lines | forms {forms}")
    print(f"RESULT body text inside the export: {body_in_export}")

    # -- the negative result: restore the pre-purge copy ----------------
    restore = root / "restored"
    restore.mkdir()
    shutil.copy2(root / b1["audit"]["path"], restore / audit_db.name)
    shutil.copy2(root / b1["content"]["path"], restore / content_db.name)
    r_chain = AuditChain(db_path=str(restore / audit_db.name))
    r_content = ContentStore(str(restore / content_db.name))

    print(f"RESULT restored records: {len(r_chain._records)} | verify: {r_chain.verify()}")
    print(f"RESULT restored c1 status: {r_content.status(h1)}")
    restored_body = r_content.open_body(h1)
    print(f"RESULT restored body reads back: {restored_body == BODIES['c1']}")
    print(f"RESULT restored commitment opens: {r_content.verify_commitment(h1, restored_body)}")
    attestations = [r for r in r_chain._records if r.commitment == "purged-v1"]
    print(f"RESULT purge attestations in the restored chain: {len(attestations)}")
    restore_hits = count_occurrences(restore / content_db.name, BODIES["c1"])
    print(f"RESULT body bytes in the restored content store: {restore_hits}")

    # -- and a split restore: audit store from the backup, content store live
    # This is the configuration an operator actually reaches by restoring one
    # store and forgetting the other, and it is worse than the full restore
    # because the two halves now say different things about the same digest.
    split = root / "split"
    split.mkdir()
    shutil.copy2(root / b1["audit"]["path"], split / audit_db.name)
    s_chain = AuditChain(db_path=str(split / audit_db.name))
    s_content = content  # the live, purged side store
    record_forms = [r.commitment for r in s_chain._records if r.commitment != COMMITMENT_NONE]
    print(f"RESULT split restore records: {len(s_chain._records)} | verify: {s_chain.verify()}")
    print(f"RESULT split restore record forms: {record_forms} | store status: {s_content.status(h1)}")
    print(f"RESULT split restore attestations: {len([r for r in s_chain._records if r.commitment == 'purged-v1'])}")

    restored_export = root / "export-from-restored.jsonl"
    write_export(export_chain(r_chain, r_content), restored_export)
    live_rows = {(r["kind"], r.get("content_hash"), r.get("index")): r for r in map(json.loads, live_export.read_text().splitlines())}
    restored_rows = {(r["kind"], r.get("content_hash"), r.get("index")): r for r in map(json.loads, restored_export.read_text().splitlines())}
    diverged = []
    for key, row in live_rows.items():
        other = restored_rows.get(key)
        if other and other.get("status") != row.get("status"):
            diverged.append((key[1], row.get("status"), other.get("status")))
    print(f"RESULT exports disagree on: {diverged}")

    checks = [
        ("live purge holds in the store bytes", ok_live),
        ("post-purge backup carries no body", b2_hits == 0),
        ("export carries forms, never bodies", body_in_export == 0),
        ("restore brings the body back", restored_body == BODIES["c1"]),
        ("restored commitment opens", r_content.verify_commitment(h1, restored_body) is True),
        ("restored chain verifies without the attestation", len(attestations) == 0 and r_chain.verify() == (True, "OK")),
        ("exports disagree after the restore", bool(diverged)),
        # The split restore is a failure of the pair, not of either store: the
        # chain is green, the body is gone, and nothing states the contradiction.
        ("split restore contradicts itself silently", s_chain.verify() == (True, "OK") and "salted-v1" in record_forms and "purged-v1" not in record_forms
         and s_content.status(h1) == "purged"),
    ]
    for label, passed in checks:
        print(f"RESULT {label}: {passed}")
    failed = [label for label, passed in checks if not passed]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
