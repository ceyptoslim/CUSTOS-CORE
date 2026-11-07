# Purge path after the marker, measured

Re-execution of `python3 scripts/purge_path_drill.py` on `main` at `2b9296a`,
2026-11-06. This record exists because the earlier transcript,
[`2026-11-06-purge-path.md`](2026-11-06-purge-path.md), was produced at
`671825f`, before the commitment form existed on the record. That transcript is a
measurement of a build that could not classify its own attestations, so it is
kept as recorded and this one stands as the run for the current build.

The question this answers: when a reader has the records and not the side store,
can they tell that a record's content was deleted, rather than that its digest
simply does not match? Before the marker, no. `action: PURGE` is a label anyone
can write. The form is inside the preimage, so it cannot be relabelled by someone
who knows the body.

## Re-run after the marker (binding version 2)

The transcript above was produced on `feat/purge-path` at `671825f`, before the
commitment form existed on the record. So the attestation in it was written by a
build that could not classify its own deletions: a reader holding those records
without the side store saw `action: PURGE` and nothing that said, in the record
itself, that the content's absence was a deletion rather than a mismatch.

Since version 2 the attestation carries `purged-v1` inside its preimage. This is
the same drill re-executed on `main` at `2b9296a`, which contains both the purge
path and the marker:

```
RESULT chain before purge: (True, 'OK') | records: 3
RESULT markers: {'r1': 'salted-v1', 'r2': 'salted-v1', 'r3': 'salted-v1'}
RESULT record-side forms: {'r1': 'salted-v1', 'r2': 'salted-v1', 'r3': 'salted-v1'}
RESULT commitments open with the body: {'r1': True, 'r2': True, 'r3': True}
RESULT attestation: b449109ee785f11b | action: PURGE
RESULT chain after purge: (True, 'OK') | records: 4
RESULT status after purge: {'r1': 'present', 'r2': 'purged', 'r3': 'present'}
RESULT markers after purge: {'r1': 'salted-v1', 'r2': 'purged', 'r3': 'salted-v1'}
RESULT attestation record form: purged-v1 | binding: v2
RESULT attestation preimage carries commitment: True = purged-v1
RESULT attestation is a deletion, readable from the record alone: True
RESULT purged record keeps the form it was stored in: salted-v1 (salted) while the attestation says purged-v1
RESULT rows in content_bodies: 2 | rows with a salt: 2
RESULT purge row: content_hash=62088bd17439a753 reason='erasure request 2026-11-06' attestation=a6b6d4e92fc797cd
RESULT any body text left in the side store: 0
RESULT read after purge refused: content 62088bd17439a753 was purged at 1794011407.820626
RESULT restored-from-backup status: salted-v1
RESULT restored body reads back: True
RESULT restored commitment opens: True
```

The stored digests in the block (`79cfab6621ec6c65`-class values) differ between
runs and are not meant to reproduce: each record carries its own CSPRNG salt, so
every execution produces different hashes. What reproduces is the shape:
`purged-v1` on the attestation, `salted-v1` on the record it purges, the chain
green on both sides, and `any body text left in the side store: 0`. A reader
re-running this should compare the forms and the RESULT lines, not the hex.

Two things this adds beyond the original run, and one thing it corrects.

The added fact is the third line from the bottom of the record group: the
attestation's preimage carries `commitment = purged-v1`, so the deletion is
readable from the record alone. `preimage_fields` returns the key, which means it
is inside the hash and not beside it, and the same build that refuses an
unimplemented binding version can now answer "was this content deleted, or does
this digest simply not match?" without the side store.

The second added fact is the asymmetry worth stating: the purged record keeps
`salted-v1`, because that is how its content was stored, while the attestation
says `purged-v1`, because that is what happened to it. A reader combining the two
learns salted-then-purged, which is the true history. Rewriting the original
record's form to `purged-v1` would have been the tempting simplification and it
would have been a lie about the storage that produced the digest.

The correction is in the original transcript above, and it was mine: the line
counted non-empty body columns instead of looking for the purged body's bytes, so
it read `2` on a run where the purged content was gone. The current line scans
every row for the purged text, which is what "any body text left" was always
supposed to mean, and it reads `0`. A count of columns is not a search for
content, and the difference is exactly the class of defect this project files
against itself.
