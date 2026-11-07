# Export and backup, and what a restore does to an erasure

Run 2026-11-06 on `main` at `9542801`, by `python3 scripts/drills/phase11_export_backup.py`.
The driver is in the repository and needs no server: both stores are SQLite
files, so a backup is a file copy and every line below can be reproduced by a
reader.

This closes the last open piece of the retention item. The question it answers is
not whether a backup works. It is what a backup taken before an erasure does to
that erasure, and the answer is that it reverses it without leaving a trace in
the restored chain.

## The three stores, and why they are three

| unit | where it lives | what deletes it |
| --- | --- | --- |
| content body | `content_bodies.body` in the content store | `purge()` |
| salt and commitment | `content_bodies.salt` / `.commitment`, same row as the body | `purge()` |
| purge attestation | a record appended to the audit chain, `commitment: purged-v1` | nothing; it is an append |

The body and the salt are in one row of one file, which matters for the window
and is stated rather than implied: there is no configuration in this build where
a backup recovers the salt without the body, so their exposure is one unit and
not two. The attestation is in the other store and is the only one of the three
that a pre-erasure backup does not contain.

## Transcript

```
work directory: /tmp/drill-export-u4xg49o8
RESULT records before backup: 3 | verify: (True, 'OK')
RESULT content status: c1=present c2=present
RESULT backup-1 audit: 16384 bytes sha256 d12f529a66fa2644
RESULT backup-1 content: 20480 bytes sha256 fe6ce33cc94572e4
RESULT purge attestation: 8897c19105c698f2 | records: 4
RESULT live c1 status after purge: purged
RESULT live verify after purge: (True, 'OK')
RESULT body bytes left in the live content store: 0
RESULT live body readable after purge: False (ContentPurged)
RESULT backup-2 content: 20480 bytes sha256 4784af9d21292023
RESULT body bytes inside backup-2: 0
RESULT live export: 6 lines | forms ['none', 'purged-v1', 'salted-v1']
RESULT body text inside the export: 0
RESULT restored records: 3 | verify: (True, 'OK')
RESULT restored c1 status: present
RESULT restored body reads back: True
RESULT restored commitment opens: True
RESULT purge attestations in the restored chain: 0
RESULT body bytes in the restored content store: 1
RESULT split restore records: 3 | verify: (True, 'OK')
RESULT split restore record forms: ['salted-v1', 'salted-v1'] | store status: purged
RESULT split restore attestations: 0
RESULT exports disagree on: [('8b6711b3f9fde933dd6cf60987adf8b8f6983623fcc2dc60d6bc9d8afd12e35a', 'purged', 'present')]
RESULT live purge holds in the store bytes: True
RESULT post-purge backup carries no body: True
RESULT export carries forms, never bodies: True
RESULT restore brings the body back: True
RESULT restored commitment opens: True
RESULT restored chain verifies without the attestation: True
RESULT exports disagree after the restore: True
RESULT split restore contradicts itself silently: True
```

The backup digests and the attestation hash differ between runs, for the reason
the purge re-run records: salts are CSPRNG per record, so the files and the
records derived from them are not byte-identical run to run. What reproduces is
every RESULT line and its direction, and the seven booleans at the end.

Two lines worth separating from the rest because they are the ones that decide
whether any of this means anything. `body bytes left in the live content store:
0` is a raw byte search of the store file, not a query through the store: a row
deleted in the query view can leave its bytes in the file, and the file is what a
copy copies. And `restore brings the body back: True` is the negative result,
read from the restored store rather than inferred.

## The negative result, stated

A copy of the content store taken before the purge, restored after it, returns
the body and the salt. The commitment opens again. The restored audit chain
verifies `(True, 'OK')` over three records and contains zero purge attestations,
because the attestation was appended after the backup. So the restored
configuration is indistinguishable, from the inside, from a store where no
erasure was ever requested.

That is the whole of the residual, and it is not repairable by a control inside
the store: a backup is a copy of history, and history before the erasure contains
the data. The erasure is complete only when the copies are gone, which makes
backup retention the operator's deletion policy whether or not it is written
down as one.

There is a second configuration, and it is worse than the first because it is
silent in a different way. Restoring the audit store from the pre-erasure backup
while the content store stays live, which is what an operator reaches by
restoring one store and forgetting the other, gives a chain that verifies
`(True, 'OK')`, records whose `commitment` says `salted-v1`, and a side store
that says `purged`. `verify()` has no opinion on the disagreement because it
never consults the side store, so nothing in the build reports it:

```
RESULT split restore records: 3 | verify: (True, 'OK')
RESULT split restore record forms: ['salted-v1', 'salted-v1'] | store status: purged
RESULT split restore attestations: 0
```

A record claiming a form its store does not hold is exactly the classification
failure the commitment marker was added to prevent, arriving through restore
rather than through a writer. It is filed as issue 136.

## Recovery window, per store

The window is the period during which a unit can still be recovered by a copy,
measured from the moment it existed. Nothing here is a retention policy; these
are the mechanics a policy has to be written against.

| unit | recoverable from | unrecoverable after |
| --- | --- | --- |
| content body | any copy of the content store taken before the purge | every such copy is destroyed |
| salt and commitment | the same copies, because they are in the same row as the body | the same moment as the body |
| purge attestation | copies of the audit store taken **after** the purge | the audit store is restored to a point before the purge, or the tail is lost |
| decision records (no content) | copies of the audit store taken after each record | the last record not in a copy, which is the phase 6 residual of the served-path drill |

Two consequences follow and neither is symmetric, which is the point. The
attestation's window is the inverse of the body's: a copy that recovers the body
is the same copy that loses the record of its deletion. An operator who keeps one
backup set cannot satisfy both halves of an erasure, because the newest set
contains the attestation and not the body while every older set contains the body
and not the attestation. Deleting the older sets is the erasure; that is the
decision, and it belongs to whoever owns the data rather than to the store.

And the attestation has one gap of its own, unmeasured here and named because it
comes from the code's ordering rather than from a run: `purge()` deletes the body
and salt first and appends the attestation second, so a crash between the two
leaves a deletion with no record of who requested it or why. The purge record
states that ordering as deliberate, on the ground that an attestation for a body
still readable is worse. Both halves of that trade are real.

## What the export carries, and what it must not

The export is the record side plus the side store's inventory: index, action,
commitment form, record hash, previous hash for each record, and content hash,
status and marker for each stored digest. It carries no bodies and no salts,
deliberately, because an export that carried either would be a second copy of the
data an erasure exists to remove. Measured: `body text inside the export: 0`
across six lines, with all three forms present (`none`, `purged-v1`,
`salted-v1`), so a consumer can tell which digests have a body available, which
were deleted deliberately, and which were never content-bound.

The export is also the only artifact that catches a restore. Comparing the live
export to one taken after restoring an older copy shows the divergence
`purged → present` for the erased digest, which is the erasure register: an
operator who keeps exports, and compares them, can see a restored store undoing a
deletion. Nothing else in the build can, and a register that is kept and never
compared establishes nothing.

## What this run does not establish

It does not establish that a backup is complete, and the wording matters: Phase 6 of the served-path drill
already records that a copy with its last row removed verifies green, and that
distinguishing a complete copy from a truncated one needs external head
anchoring, which the build does not have. This run inherits that limit rather
than restating it as loaded.

It does not measure a PostgreSQL backup. The windows above are properties of
*when* a copy was taken, not of how, so they carry to `pg_dump` of the audit
store, but the file sizes and digests in the transcript are SQLite and a reader
should not treat them as claims about a dump.

And it binds content through the store API rather than through the service. The
served path records `commitment: none` on every decision, because `/v1/evaluate`
keeps no content at all, so there is nothing for the service to purge yet. That
is a wiring gap and not a property of this drill: the purge path exists, the
store exists, and the endpoint that would call them does not. It is filed as
issue 137, and no erasure claim about the served path should be made until it is
closed.
