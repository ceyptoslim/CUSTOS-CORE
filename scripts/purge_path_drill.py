#!/usr/bin/env python3
"""The purge-path drill, executable rather than transcribed.

docs/restore-drills/2026-11-06-purge-path.md used to quote a script that lived in
/tmp, which meant the transcript could not be re-run by a reader and could not be
re-checked against a later build. This is that script, in the repository, and the
drill document quotes its output.

What it exercises: three records through AuditChain.record with each body stored
first through ContentStore.put, so the record's content_hash and the side store's
key are the same value; the store copied to a file as a backup would hold it; one
body purged; the chain verified across the deletion; and the copy restored to show
what a purge does not reach.

Since binding version 2 the attestation also carries the commitment form inside
its preimage, so a reader holding records without the side store can classify the
attestation as a deletion rather than infer it from the action name. The run
prints that on the record side, which the original transcript could not, because
it was written against a build that had no such field.

Run: python3 scripts/purge_path_drill.py

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custos.audit import (  # noqa: E402
    COMMITMENT_PURGED_V1,
    COMMITMENT_SALTED_V1,
    AuditChain,
    preimage_fields,
)
from custos.retention import ContentStore  # noqa: E402


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="purgedrill-")
    store_path = os.path.join(workdir, "content.sqlite")
    chain_path = os.path.join(workdir, "audit.sqlite")

    store = ContentStore(store_path)
    chain = AuditChain(db_path=chain_path)

    bodies = {
        "r1": "transfer 250 to vendor acme",
        "r2": "transfer 900 to vendor globex",
        "r3": "transfer 40 to vendor initech",
    }
    records = {}
    for name, body in bodies.items():
        records[name] = store.put_and_record(
            body, chain=chain, client_id="drill", action="ALLOW", reason="policy"
        )

    hashes = {name: rec.content_hash for name, rec in records.items()}
    ok_before, why_before = chain.verify()
    print(f"RESULT chain before purge: ({ok_before}, '{why_before}') | records: {len(chain._records)}")
    print(f"RESULT markers: { {n: store.marker(h) for n, h in hashes.items()} }")
    print(f"RESULT record-side forms: { {n: r.commitment for n, r in records.items()} }")
    print(
        "RESULT commitments open with the body: "
        f"{ {n: store.verify_commitment(hashes[n], bodies[n]) for n in bodies} }"
    )

    backup_path = os.path.join(workdir, "content.bak.sqlite")
    shutil.copyfile(store_path, backup_path)

    purge_reason = "erasure request 2026-11-06"
    attestation_hash = store.purge(
        hashes["r2"], chain=chain, client_id="ops", reason=purge_reason
    )
    attestation = chain._records[-1]
    assert attestation.record_hash == attestation_hash

    ok_after, why_after = chain.verify()
    print(f"RESULT attestation: {attestation.record_hash[:16]} | action: {attestation.action}")
    print(f"RESULT chain after purge: ({ok_after}, '{why_after}') | records: {len(chain._records)}")
    print(f"RESULT status after purge: { {n: store.status(h) for n, h in hashes.items()} }")
    print(f"RESULT markers after purge: { {n: store.marker(h) for n, h in hashes.items()} }")

    # The record side: what a reader holding records without the store can see.
    fields = preimage_fields(attestation, attestation.previous_hash)
    print(
        "RESULT attestation record form: "
        f"{attestation.commitment} | binding: v{attestation.binding_version}"
    )
    print(
        "RESULT attestation preimage carries commitment: "
        f"{'commitment' in fields} = {fields.get('commitment')}"
    )
    print(
        "RESULT attestation is a deletion, readable from the record alone: "
        f"{fields.get('commitment') == COMMITMENT_PURGED_V1}"
    )
    print(
        "RESULT purged record keeps the form it was stored in: "
        f"{records['r2'].commitment} (salted) while the attestation says {attestation.commitment}"
    )
    assert records["r2"].commitment == COMMITMENT_SALTED_V1

    with store._connect() as conn:
        rows = conn.execute("SELECT COUNT(*) FROM content_bodies").fetchone()[0]
        salted = conn.execute(
            "SELECT COUNT(*) FROM content_bodies WHERE salt IS NOT NULL"
        ).fetchone()[0]
        # A scan for the purged body's bytes anywhere in the store, not a count of
        # empty rows: a body that reappeared under a different key would still be
        # the body, and the first draft of this line counted columns instead of
        # looking for content.
        left = sum(
            1
            for row in conn.execute("SELECT body FROM content_bodies").fetchall()
            if row["body"] and bodies["r2"] in row["body"]
        )
    print(f"RESULT rows in content_bodies: {rows} | rows with a salt: {salted}")
    print(
        f"RESULT purge row: content_hash={hashes['r2'][:16]} reason={purge_reason!r} "
        f"attestation={attestation.record_hash[:16]}"
    )
    print(f"RESULT any body text left in the side store: {left}")

    try:
        store.open_body(hashes["r2"])
    except Exception as exc:  # noqa: BLE001 - the message is the result
        print(f"RESULT read after purge refused: {exc}")

    # The copy problem: restore the backup taken before the purge.
    restore_dir = tempfile.mkdtemp(prefix="purgedrill-restore-", dir=workdir)
    restored_path = os.path.join(restore_dir, "content.sqlite")
    shutil.copyfile(backup_path, restored_path)
    restored = ContentStore(restored_path)
    print(f"RESULT restored-from-backup status: {restored.marker(hashes['r2'])}")
    restored_body = restored.open_body(hashes["r2"])
    print(f"RESULT restored body reads back: {restored_body == bodies['r2']}")
    print(f"RESULT restored commitment opens: {restored.verify_commitment(hashes['r2'], bodies['r2'])}")

    print(f"RESULT workdir: {workdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
