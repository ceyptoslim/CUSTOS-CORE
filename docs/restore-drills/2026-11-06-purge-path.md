> **Note on the record.** This is the transcript as run, on `feat/purge-path` at
> `671825f`, before the commitment form existed on the record. It is kept exactly
> as recorded rather than edited, including the temporary script path it names.
> The run for the current build, which carries the attestation's form inside its
> preimage, is
> [`2026-11-06-purge-path-post-marker.md`](2026-11-06-purge-path-post-marker.md).

# Purge path, measured

Run 2026-11-06 on branch `feat/purge-path`, cut from `main` at `671825f`. This is
the run for the retention item: content separation, salted commitments, a purge
that deletes the body and the salt together, an attestation appended to the
chain, and the copy problem measured rather than argued.

The record binds `content_hash` and never holds the content, so the chain hashes
nothing a purge touches. That separation was already true before this change; what
did not exist was anywhere to hold the body, which is the same as saying nothing
could be purged.

## What was run

```
python3 /tmp/purgedrill/run.py
```

Three records through `AuditChain.record`, each body stored first through
`ContentStore.put`, so the record's `content_hash` and the side store's key are
the same value. Then the store is copied to a file, which is what a backup would
hold, and one of the three bodies is purged.

## Output

```
RESULT chain before purge: (True, 'OK') | records: 3
RESULT markers: {'r1': 'salted-v1', 'r2': 'salted-v1', 'r3': 'salted-v1'}
RESULT commitments open with the body: {'r1': True, 'r2': True, 'r3': True}
RESULT attestation: 6d9bab8f4585d0e0 | action: PURGE
RESULT chain after purge: (True, 'OK') | records: 4
RESULT status after purge: {'r1': 'present', 'r2': 'purged', 'r3': 'present'}
RESULT markers after purge: {'r1': 'salted-v1', 'r2': 'purged', 'r3': 'salted-v1'}
RESULT rows in content_bodies: 2 | rows with a salt: 2
RESULT purge row: content_hash=0900c3614326eb05 reason='erasure request 2026-11-06' attestation=6d9bab8f4585d0e0
RESULT any body text left in the side store: 0
RESULT read after purge refused: content 0900c3614326eb05 was purged at 1794007303.6781476
RESULT restored-from-backup status: salted-v1
RESULT restored body reads back: True
RESULT restored commitment opens: True
```

## What the run establishes

A purge deletes the body and the salt in one operation, and the chain verifies
record for record across it: three records before, four after, `(True, 'OK')`
both times, with the fourth an attestation whose `content_hash` is the value the
purged record binds. The attestation is attributable, which is what makes a
deletion reviewable without the content: a reader can see that record
`0900c3614326eb05` was purged, when, under what reason, and which chain record
says so.

The three states are distinguishable after the fact, read from the store rather
than inferred: `present`, `purged`, and `unknown` for a hash the store never held.
Reading purged content is refused with the purge time rather than returning an
empty body, and verifying a purged commitment raises instead of returning
`False`, because an absence and a mismatch are different findings and reporting
one as the other is the defect this project keeps finding in describing layers.

The commitments are salted per record with `secrets.token_bytes`, generated and
never derived, and the marker is digested with the body rather than stored
alongside it. Two writers storing the same body produce the same `content_hash`
(identity is the content, as the record expects) and different commitment
digests, so the stored digest is not linkable by the stored value alone. Re-offering
a purged body is refused rather than stored again, since a purge that a second
submission undoes is not a purge.

## What the run does not establish

**The copy problem.** Restoring the copy taken before the purge brings the body
and the salt back, and the commitment opens again:

```
RESULT restored-from-backup status: salted-v1
RESULT restored body reads back: True
RESULT restored commitment opens: True
```

That is the residual, measured. A purge reaches the live side store and nothing
else. Any backup, replica, or snapshot taken before the deletion holds the body
and the salt, and restoring it resurrects both. Destroying the salt in the live
store is a deletion control against the live store only. Closing the copy problem
requires a purge that reaches every copy before the purge is recorded as
complete, or a store whose copies never contained the body, and neither exists in
this build. The attestation above should therefore be read as "the live store no
longer holds this", not as "this content no longer exists".

**Who else can delete.** A writer with access to the side store can delete a body
without appending an attestation, and a reader looking only at the chain would
see a record whose content is missing with no record of why. The attestation is
produced by this module, not enforced by the store: the ordering inside `purge`
is delete-then-attest, and a crash between the two leaves an unrecorded
deletion. Making that unwitnessable requires the deletion and the attestation to
be one transaction across two stores, which they are not.

**Tenancy.** The side store is one file. Two tenants sharing it would share a
namespace, so a purge in one tenant could delete content the other recorded. The
chain's tenant scoping landed separately; the side store does not yet have it.

**Retention schedules.** Nothing here runs on a timer, and nothing enforces a
maximum age. This is the mechanism a schedule would call, not the schedule.

**Wiring.** The served path does not call this module. `/v1/evaluate` hashes the
content and stores nothing, so today no request creates a body that could be
purged. The run above drives `ContentStore` directly. What this establishes is
that the retention mechanism works when something calls it, and what remains is
the decision about what the service is willing to keep in order to be able to
purge it.
