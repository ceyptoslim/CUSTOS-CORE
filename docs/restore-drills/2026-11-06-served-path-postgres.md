# Restore drill on the served path, PostgreSQL

Run 2026-11-06 on `main` at `5b4994e` (merge of #123, the durable wiring). This is
the transcript for item 1: a production process writing through `/v1/evaluate`,
a restart, a backup, a restore into a fresh database, a fresh process verifying
the restored chain, and the restored store continuing to accept records.

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

## What an operator should take from this

Restart survival and restore are both demonstrated on the served path with
PostgreSQL. Completeness is not, and cannot be claimed from the store alone. A
pilot that needs to distinguish a truncated history from a complete one needs
the head published somewhere the writer cannot reach, which is the piece this
build does not have.
