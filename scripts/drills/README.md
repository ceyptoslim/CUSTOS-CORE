# Drill drivers

The injections behind the item 1 closure. They were run from a temporary
directory the first time, which meant a reader could check the transcript against
the numbers but not against the code, and could not re-run either. They live here
now.

Each one drives the **served path** through `FastAPI TestClient`, not the library
directly, because the claim being tested is about what the service does when a
process dies, a disk fills, or two replicas share a store.

Prerequisites: a Python environment with the project dependencies, and either
`DATABASE_URL` (Phases 8 and 10) or `AUDIT_DB_PATH` (Phase 9).

## Phase 8: killed mid-append

```
DATABASE_URL=postgresql://user:pass@host:port/db \
  python3 scripts/drills/phase8_kill_mid_append.py
```

Spawns `writer_loop.py`, waits `DRILL_SECONDS` (default 3), sends `SIGKILL`, then
counts what the store holds from a new process. Reproduced 2026-11-06 on an empty
database: **98 acknowledged, 99 durable, 0 torn rows, verify `[True, 'OK']`** from
a fresh process. The gap is the result: the store committed a record after the
last acknowledgement was printed, so acknowledged is a subset of durable rather
than the reverse.

## Phase 9: the store fills mid-append

```
gcc -shared -fPIC -O2 -o /tmp/enospc.so scripts/drills/enospc.c -ldl
CUSTOS_ENV=production CUSTOS_JWT_SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))') \
AUDIT_DB_PATH=/tmp/drill-full/audit.sqlite \
ENOSPC_AFTER=72000 ENOSPC_TARGET=audit.sqlite LD_PRELOAD=/tmp/enospc.so \
  python3 scripts/drills/phase9_disk_full.py
```

The shim returns `ENOSPC` from `write`, `pwrite`, `pwrite64` and `writev` once the
target file has taken `ENOSPC_AFTER` bytes, for that file only, so the rest of the
process keeps working. Reproduced 2026-11-06: **1 accepted, then
`OperationalError: database or disk is full`, in-process chain length 1, store
holds 1 row, `integrity_check` ok.** The in-memory chain never ran ahead of the
store.

`CUSTOS_ENV=production` matters: a dev process defaults to `InMemoryBackend`,
where there is no store to fill and the run would report a clean pass while
measuring nothing. The script refuses to run in that case rather than reporting
it.

## Phase 10: two replicas, one store

```
DATABASE_URL=postgresql://user:pass@host:port/db \
  python3 scripts/drills/phase10_two_writers.py
```

Warms the schema with one boot, then starts `phase10_worker.py` twice, waits for
both to report the head they loaded, and only then lets either append. Reproduced
2026-11-06: **A appended 200, B refused with `ChainForkError`, B's in-process
chain length 0, fresh process verifies `[True, 'OK']` with clients `['A']`.**

The warm-up is deliberate. Two cold starts against an empty database used to race
in schema creation (`pg_type_typname_nsp_index`, issue 131) and one process died
there, upstream of the chain and before the fork guard, which made that failure
look like the guard working: a false pass. The race is fixed now, and the warm-up
stays, because this phase is about the fork condition and should not acquire a
second reason to fail. The race itself is phase 13.

## Phase 13: two cold starts on an empty database (PostgreSQL)

```
DATABASE_URL=postgresql://user:pass@host:port/db \
  python3 scripts/drills/phase13_cold_start_race.py
```

The inverse of phase 10: no warm-up, no stagger, an empty scratch schema every
trial, and both processes released at the same wall-clock instant. This is the
defect the phase 10 warm-up was working around, measured directly.

Pass condition, per trial: both processes reach the end of schema creation,
exactly one append lands, and the other is refused at the store with
`ChainForkError`.

Measured 2026-11-06 on `main` at `40d6519`: **5/5 trials, both processes up, one
append each.** The same driver on `58c7462`, before the advisory lock, **fails 5/5
trials** with

```
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint
  "pg_type_typname_nsp_index"
```

which is the mutation check for the fix rather than for the unit test that models
it. Those five results are what closed issue 131.

It needs a real server and refuses without one: the duplicate-key error comes from
the PostgreSQL catalogs, so no store this repository can fake will produce it. The
driver creates and drops its own `drill_cold_*` schemas and touches nothing else.

## Phase 11: export and backup, and the restored-from-backup negative result

```
python3 scripts/drills/phase11_export_backup.py
```

No prerequisites beyond the project dependencies, and no server: both stores are
SQLite files, so a backup is a file copy. The run writes three records (two with
content, one without), backs up both stores, purges one body, backs up again,
exports the record side plus the store inventory, then restores the pre-purge
copy and measures what the restore did to the erasure.

Reproduced 2026-11-06: **live purge holds (`0` body bytes in the store file),
post-purge backup carries no body, export carries forms and no bodies, and the
restore brings the body back with the commitment opening again while the restored
chain verifies `(True, 'OK')` with zero purge attestations.** The record is
`docs/restore-drills/2026-11-06-export-backup.md`.

It also measures a split restore, audit store from the backup and content store
live, which produces a chain that verifies green while its records say
`salted-v1` and its store says `purged` (issue 136). The script's preconditions
are asserted and a failed check reaches the exit code, per the rule that came out
of the InMemoryBackend pass.

## What these do not show

The store must be one writer at a time for these results to mean what they say.
The guard is a unique index on `previous_hash` (per tenant), which is construction
rather than convention, but a writer with direct store access can still rewrite a
chain consistently and verify green, and truncation stays invisible. Both need
external head anchoring, which this build does not have.
