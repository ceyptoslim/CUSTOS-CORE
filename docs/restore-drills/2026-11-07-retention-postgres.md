# Retention on the served path, on PostgreSQL

Run 2026-11-07, by `python3 scripts/drills/phase14_retention_postgres.py`, against
PostgreSQL 15.19 on the local socket. The driver is in the repository, creates and
drops its own `drill_retention_*` database, and exits non-zero if any check below is
false.

This is the run issue 149 named. Phase 12 answers the same questions on SQLite
because its pre-purge copy is a file copy of the audit store, which a server is not;
here that one step is `pg_dump` and the restore is a reload into a fresh database.
Everything else is the same sequence over HTTP.

## What was measured

```
RESULT scratch database created: drill_retention_bd3db53f
RESULT audit backend = PostgreSQLBackend
RESULT /v1/info content_retention = store
RESULT evaluate status 200
RESULT record commitment = salted-v1 | binding_version 2
RESULT body bytes in the content store = 1
RESULT reconcile before purge ok = True
RESULT pg_dump exit 0 | bytes 6432
RESULT purge without the admin token status 401
RESULT purge status 200 | store_status purged
RESULT body bytes in the content store after purge = 0
RESULT attestation appended = PURGE
RESULT reconcile after purge ok = True
RESULT pg_restore exit 0
RESULT split restore: /v1/audit/verify = {'valid': True, 'reason': 'OK', 'chain_length': 1, 'tenant_id': 'default', 'backend': 'PostgreSQLBackend'}
RESULT split restore: status ok = False | findings ['unattested-purge']
RESULT resubmitting purged content status 200
RESULT resubmission commitment = none
RESULT body bytes after resubmission = 0
RESULT scratch database dropped: drill_retention_bd3db53f
RESULT the decision is recorded on the PostgreSQL chain: True
RESULT the record names the form the store used: True
RESULT the body is in the content store: True
RESULT the pair reconciles clean before the purge: True
RESULT the pre-purge copy is a dump that exists: True
RESULT an unauthenticated erasure is refused: True
RESULT the erasure succeeds: True
RESULT the body is gone from the store: True
RESULT the attestation is in the PostgreSQL chain: True
RESULT the pair reconciles clean after the purge: True
RESULT the restored chain verifies on its own terms: True
RESULT the split restore is reported by name: True
RESULT a purged body is still decided: True
RESULT its new record says none: True
RESULT it does not re-hold the bytes: True
RESULT every check: 15 of 15 true on PostgreSQL
```

The interesting line for a reader who knows phase 12 is `pg_restore exit 0` followed
by a verify of a one-record chain beside a store that is past it. That is the split
restore on a server: the chain was restored to the point before the erasure, the
content store stayed after it, and the pair is reported as `unattested-purge` rather
than verifying green over a shorter history.

## What this does not cover

One host, one process, one tenant, a local socket, and a content store on local disk.
It is not a pooled cluster, not a second replica, and not a rolling replacement. The
content store is still one SQLite file per tenant beside the process, so a deployment
that put the audit chain in PostgreSQL and ran two replicas would have one shared
chain and two stores, and this drill says nothing about that shape.

The split restore also remains the shape phase 12 records: it is reported by name,
not prevented, and `verify` still answers only the question it was asked, which is
whether the records link.

## Why it needed its own driver

Making phase 12 do this would have given one phase two backup mechanisms and one
refusal for a configuration it could then handle. The two drills share a sequence and
nothing else: one takes a copy with `cp`, the other with `pg_dump`, and the second
needs a server, a client binary and a database it is allowed to create.
