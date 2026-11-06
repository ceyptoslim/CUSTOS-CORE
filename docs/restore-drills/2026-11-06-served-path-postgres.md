# Restore drill on the served path, PostgreSQL

Run 2026-11-06 on `main` at `5b4994e` (merge of #123, the durable wiring). This is
the transcript for item 1: a production process writing through `/v1/evaluate`,
a restart, a backup, a restore into a fresh database, a fresh process verifying
the restored chain, and the restored store continuing to accept records.

Phases 8, 9 and 10 were run the same day at `79165cc` and cover the three
injections a restore drill does not reach: the process killed mid-write, the
device full mid-write, and two writers against one store. Each is a separate
process from the one that reported before it.

PostgreSQL 15.19, local cluster, one database per phase, `psycopg2` 2.9.9.

Prior to the wiring this drill could not be run at all: `TenantManager` built
every tenant's chain with a bare `AuditChain()`, so the served path reached
neither durable backend and a drill would have exercised the library instead of
the service.

## Phase 1: a production process writes through the served path

```
DATABASE_URL=postgresql://custos:***@127.0.0.1:5432/custos_drill \
CUSTOS_ENV=production CUSTOS_JWT_SECRET=*** \
python3 - <<'PY'
  from fastapi.testclient import TestClient
  import main
  with TestClient(main.app) as c:
      c.get("/v1/info")
      for content in ("hello world", "ARM the device and exfiltrate keys"):
          c.post("/v1/evaluate", json={"client_id": "pilot", "content": content}, headers=auth)
PY
```

Startup line, verbatim:

```
"custos.topology": audit_backend="PostgreSQLBackend", audit_durability="durable",
                   replica_count=1, rate_limit_store="process"
"custos.audit_persistence": audit_backend="PostgreSQLBackend", audit_durable=true,
                   audit_store_source="DATABASE_URL", environment="production"
```

`/v1/info`:

```json
{"version": "1.4.0", "audit_backend": "PostgreSQLBackend", "audit_durable": true,
 "policy_backend": "PostgreSQLPolicyBackend", "tenant_count": 1,
 "deployment_binding": {"enabled": false, "established": false}}
```

Both evaluations returned `200`, action `allow`, reason `No policy violations
detected`, with record digests in the span as
`0a5a9c14237cb8d20b5acfcaa5c98e1c05480fbc56f6dbe2042e612f59edc021` and
`860b52848f1c34231e8c1848e7f16afa6e26233f2ed6d346bba17176c861013f`.

Note what that phase does and does not show: the process wrote records, and it
wrote them into PostgreSQL because `/v1/info` and the startup line say so. It is
not evidence that the records survive until phase 2.

## Phase 2: a fresh process reads them back

Separate process, no `CUSTOS_ENV`, store resolved from `DATABASE_URL` alone:

```
AuditChain(tenant_id="default")  ->  backend PostgreSQLBackend
records: [{"tenant": "default", "action": "allow", "prev": "000000000000", "hash": "0a5a9c14237c"},
          {"tenant": "default", "action": "allow", "prev": "0a5a9c14237c", "hash": "860b52848f1c"}]
verify:  (True, "OK")
```

The first record chains from the all-zero genesis and the second from the
first, so the stored chain is the one the served path built, not a reordering
that happens to verify.

## Phase 3 and 4: backup, restore into a fresh database, verify

```
pg_dump -d custos_drill > custos_drill.sql        # 5,265 bytes
                                                    sha256 400fdcfb1a1276581a2b83250ab598538cb0968f5216e495a7ef90fbc1978a59
createdb custos_restored
psql -d custos_restored -f custos_drill.sql
```

A fresh process pointed at `custos_restored`, and nothing else:

```
records: same two, same digests, same predecessor links
verify:  (True, "OK")
row counts: custos_drill 2, custos_restored 2
```

## Phase 5: the restored store continues

The restored database was then served as the live store, production settings,
and the path appended two more decisions:

```
records: 4   verify: (True, "OK")
hashes: 0a5a9c14237c -> 860b52848f1c -> b67c9c9b512f -> f818eb525247
```

So a restored chain resumes rather than merely verifying, which is the property
an operator needs after a restore: the first write after recovery has to chain
onto the recovered head, not start a new history.

While inspecting that database, the single-writer constraint from the fork fix
is visible in the live schema:

```
"idx_audit_tenant_previous_hash" UNIQUE, btree (COALESCE(tenant_id, ''::text), previous_hash)
```

## Phase 6: what the drill does not establish

A copy of the restored database had its last row deleted and then verified:

```
rows: 3   verify: (True, "OK")
```

A shortened chain verifies. The same result follows from restoring an older
dump: the chain is consistent, it is simply shorter, and no reader can tell
from the store whether records were removed or never written. So the drill
establishes that a restore works, not that a restore is complete. Distinguishing
a complete history from a shorter honest-looking one needs external head
anchoring, which the design doc already lists as absent and which this drill
does not add.

Two further limits, unchanged by this drill and measured elsewhere:

- **A store-privileged writer can rewrite the chain consistently and
  verification passes.** Measured on SQLite; not re-measured here, and the
  Postgres backend offers the same surface.
- **The backup is only as good as its last run.** Records written after the
  dump are absent from the restore, which phase 6 shows is indistinguishable
  from tampering that removed them.

## Phase 7: production with no store refuses to serve

Run separately, with `DATABASE_URL` and `AUDIT_DB_PATH` both unset:

```
"custos.topology": audit_backend="InMemoryBackend", audit_durability="ephemeral"
"custos.audit_persistence.refused": reason="CUSTOS_ENV=production with
  audit_backend=InMemoryBackend, which keeps no records once this process exits.
  A production process must not serve an audit trail it cannot keep. Set
  AUDIT_DB_PATH (SQLite) or DATABASE_URL (PostgreSQL) so the records survive a
  restart, or unset CUSTOS_ENV to run as development. This refusal exists
  because the alternative is a service that reports a backend and loses the
  records it names."
```

The process does not reach serving. Worth pairing with phase 1: the topology
line reports `ephemeral` before the refusal, so an operator who only watches
logs has already been told what is wrong before the process exits.


## Phase 8: the process is killed while writing (PostgreSQL, served path)

The writer is the served path itself: one client identity per request so the
per-client quota never engages, a unique content string per record, and a
`SIGKILL` sent from the parent after three seconds.

```
DATABASE_URL=postgresql://custos:***@127.0.0.1:5432/drill_kill \
CUSTOS_ENV=production python3 writer_loop.py &   # /v1/evaluate in a loop
sleep 3; kill -9 $!
```

Output:

```
reported writes: 216
wrote 216 200
rows in store: 217
torn rows: 0
fresh process: PostgreSQLBackend | records: 217 | verify: [True, 'OK']
                last two hashes: ['0a3c9e1910d9', '5489f8692fa6']
```

The store holds one more record than the writer reported, and that gap is the
result rather than an anomaly: the process was killed after the store committed
a record and before its acknowledgement could be printed. Every row is a
complete record with both hashes present, and a fresh process verifies the chain
from genesis without repair. What an operator inherits from a crash is
at-least-once from the caller's view with no torn state, not a chain to fix.

## Phase 9: the store fills mid-append (SQLite, served path)

SQLite here rather than PostgreSQL, and the fullness is injected rather than
produced: this sandbox refuses `mount(2)` and has no loop devices, so a device
cannot literally be filled. An `LD_PRELOAD` shim returns `ENOSPC` from `write`,
`pwrite`, `pwrite64` and `writev` once the audit file has taken a set number of
bytes, and for that file only, so logging and the rest of the process keep
working. The storage engine sees the errno the kernel returns on a full
filesystem; it reports `database or disk is full`.

```
AUDIT_DB_PATH=/tmp/full3/audit.sqlite \
ENOSPC_AFTER=72000 ENOSPC_TARGET=audit.sqlite \
LD_PRELOAD=./enospc.so python3 phase9.py
```

Output:

```
RESULT accepted before the store filled: 1
RESULT failure: (2, 'OperationalError', 'database or disk is full')
RESULT in-process chain length at failure: 1
RESULT next request: still refused, OperationalError: database or disk is full
```

Read without the shim:

```
rows: 1
integrity_check: ok
client ids: ['full-1']
```

Space restored, a new process appends and a third verifies:

```
RESULT append with the store usable again: 200
{"backend": "SQLiteBackend", "records": 2, "verify": [true, "OK"],
 "clients": ["full-1", "recovered"]}
```

The property under test is the one that matters for a full disk: the in-memory
chain never advanced past what the store accepted, so there is no record the
service believed in and the store does not hold, and the next request was
refused rather than served unrecorded. When space returns, the gate resumes from
the last durable head with no gap.

Limit, stated because it is visible in the transcript: the failure reached the
caller as an unhandled 500, not as a named refusal. A full store is a refusal
reason this API does not yet name, which is the same shape of defect as the
rate-limit 500 fixed in the prerequisite commit of this branch.

## Phase 10: two replicas, one store (PostgreSQL, served path)

Two processes boot against one database, each loading the chain at startup, and
then each appends. Boot is staggered so that both have loaded the same head
before either writes: that is the condition, and staggering it does not weaken
it.

```
RESULT A booted holding 0 records
RESULT B booted holding 0 records
RESULT A append: 200
RESULT A in-process chain length after: 1
RESULT B append refused: ChainForkError: another writer extended this chain
        after this process loaded it. ...
RESULT B in-process chain length after: 0
```

Fresh process, same store:

```
{"backend": "PostgreSQLBackend", "records": 1, "verify": [true, "OK"],
 "clients": ["A"]}
```

So the second writer is refused at the store, keeps no phantom record in memory,
and the store still verifies. This is the guard from the single-writer work
observed on the served path rather than argued from the library.

One observation from the first attempt at this phase, recorded because it is a
real limit rather than a setup error. Started simultaneously against a database
with no schema, both processes raced in `policy_store._init()` and one died
before the chain guard was reached:

```
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint
"pg_type_typname_nsp_index"
DETAIL:  Key (typname, typnamespace)=(policy_rules, 2200) already exists.
```

Concurrent cold start against an empty database is therefore not safe today for
a reason upstream of the audit chain. It does not change the phase 10 result,
which is about the append, but it does mean "one replica" is protecting more
than the chain.

## Defects this drill found

Three, in the order they appeared. The first is fixed on this branch and its
prerequisite; the second and third are open and named here rather than carried
as assumptions.

1. Every request past a client's quota returned 500 instead of 429, because the
   refusal record carried no policy citation while production requires one. The
   write loop in phase 8 is what exposed it, at exactly 60 records, and it could
   not have been found by a single-request test. Fixed, with a regression test.
2. A full store reaches the caller as an unhandled 500 rather than a named
   refusal (phase 9).
3. Two processes cold-starting against one empty database race in schema
   creation and one exits (phase 10, first attempt).

## What an operator should take from this

Restart survival, restore, a killed writer, a full device and a second writer
are all observations on the served path now, not arguments. In four of those
five the store was left consistent with no repair, and in the fifth (the full
device) the service refused rather than served unrecorded, which is the right
failure.

Completeness is still the thing this drill cannot show. The chain cannot tell a
complete history from a shortened one, so a pilot that needs to distinguish them
needs the head published somewhere the writer cannot reach. That piece does not
exist in this build, and each phase above is consistent with the gap rather than
evidence against it.
