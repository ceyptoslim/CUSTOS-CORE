# Easing the content out of the served path, over HTTP

Run 2026-11-06, by `python3 scripts/drills/phase12_served_path_retention.py`.
The driver is in the repository, needs no server, and exits non-zero if any
check below is false. Auth is on by default, so every call carries a bearer token
minted for the same client id it declares, and both admin credentials where the
endpoint needs them.

This closes the last open piece of the retention item: whether the served path
keeps the content it reads, and whether an erasure request against it acts on
anything.

## Two runs of one API, differing only in configuration

| run | configuration | what a record says | what an erasure request gets |
| --- | --- | --- | --- |
| retention off | `CUSTOS_CONTENT_RETENTION=off` | `commitment: none` | `503`, naming that nothing was kept |
| retention store | `=store`, plus a store directory and an admin token | `commitment: salted-v1` | `200`, body gone from the file, `purged-v1` attestation appended |

The distinction that matters is not that one mode stores and the other does not.
It is that in each mode the record and the store agree, and the disagreement that
used to be silent is now named.

## The split restore, over HTTP

The last block is the defect this run was extended to cover. The audit store is
rolled back to a copy taken before the erasure while the content store stays past
it. `/v1/audit/verify` still answers `valid: True` over the shorter chain, which is
correct for what it claims, and `GET /v1/retention/status` answers
`ok: false, findings: ['unattested-purge']`, which is the missing statement.

## What the run establishes

- A record cannot claim a stored form the store did not use: the form is read from
  the store it was written to.
- An erasure through the API removes the bytes from the file, not merely from a
  view, and leaves an attestation the chain can attribute.
- A restored chain beside a live store is reported by name rather than verifying
  green in silence, and the reporting does not require `verify()` to change what
  it says.
- A tenant id that is legal but not a filename (the drill uses a space) evaluates
  normally. Refusing it was the first implementation and it made a legal tenant a
  500 on the decision path.

## What the run does not establish

- It does not reach a copy of the content store taken before the purge; that is
  `docs/restore-drills/2026-11-06-export-backup.md`.
- It covers `/v1/evaluate_action` as of issue 140, in its own run against fresh
  stores: the proposed action is kept, purged, and a resubmission is still decided
  and says `none`. What it still does not establish is the same thing it never
  did for `/v1/evaluate`: nothing here measures a store that refuses a write
  mid-run, which is a separate guard.
- It does not measure behaviour under concurrent writers or across replicas. The
  served path is single-replica by configuration, and the refusal for that is a
  separate guard.

## Transcript

```
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.policy_factory", "message": "Using regex policy engine (CUSTOS_POLICY_ENGINE=regex)"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "enterprise.routes.not_available", "reason": "custos-enterprise not installed \u2014 public-only deployment"}
work directory: /tmp/drill-retention-8gklkk7b
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.topology", "replica_count": 1, "rate_limit_store": "process", "audit_backend": "SQLiteBackend", "shared_state_enforced": true, "audit_durability": "durable"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.audit_persistence", "audit_backend": "SQLiteBackend", "audit_durable": true, "audit_store_source": "AUDIT_DB_PATH", "environment": "development", "audit_durability_note": "records survive this process; per-tenant scoping keeps each tenant's chain separate"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.content_retention", "content_retention": "off", "content_store_dir": null, "retention_admin_configured": false, "environment": "development"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "warning", "logger": "custos.main", "message": "custos.content_retention.off", "consequence": "the served path keeps no content, so an erasure request against it has nothing to act on and is refused"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.startup", "version": "1.4.0"}
RESULT retention off: /v1/info content_retention = off
{"otel.span": {"trace_id": "ef687bc8833940acb009ecb225c669cd", "span_id": "a2f2a3f87e4d41b5", "name": "custos.evaluate", "start_time": 1794018882.281242, "end_time": 1794018882.2840965, "duration_ms": 2.85, "status": "OK", "attributes": {"client_id": "drill", "tenant_id": "default", "action": "allow", "audit_record_hash": "72edc9c0db60b9d5300d4e658ea2a4c8d95a21e02b7299be6995a0a8076c8a3c"}}}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "evaluate.complete", "client_id": "drill", "tenant_id": "default", "action": "allow", "allowed": true, "trace_id": "ef687bc8833940acb009ecb225c669cd"}
RESULT retention off: evaluate status 200
RESULT retention off: record commitment = none | binding_version 2
RESULT retention off: erasure request status 503
RESULT retention off: erasure refusal names the mode = True
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.shutdown"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.policy_factory", "message": "Using regex policy engine (CUSTOS_POLICY_ENGINE=regex)"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.topology", "replica_count": 1, "rate_limit_store": "process", "audit_backend": "SQLiteBackend", "shared_state_enforced": true, "audit_durability": "durable"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.audit_persistence", "audit_backend": "SQLiteBackend", "audit_durable": true, "audit_store_source": "AUDIT_DB_PATH", "environment": "development", "audit_durability_note": "records survive this process; per-tenant scoping keeps each tenant's chain separate"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.content_retention", "content_retention": "store", "content_store_dir": "/tmp/drill-retention-8gklkk7b/content", "retention_admin_configured": true, "environment": "development"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.startup", "version": "1.4.0"}
RESULT retention store: /v1/info content_retention = store
{"otel.span": {"trace_id": "321ced9fca3a4939bb874f9c8ff4f4fc", "span_id": "5b6accafe5c34aec", "name": "custos.evaluate", "start_time": 1794018882.3015585, "end_time": 1794018882.3039808, "duration_ms": 2.42, "status": "OK", "attributes": {"client_id": "drill", "tenant_id": "default", "action": "allow", "audit_record_hash": "9f67a6c4343162c52fb831431cd3900d7ec7d8be0ebf4e7816af7dbc1a16bdf0"}}}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "evaluate.complete", "client_id": "drill", "tenant_id": "default", "action": "allow", "allowed": true, "trace_id": "321ced9fca3a4939bb874f9c8ff4f4fc"}
RESULT retention store: record commitment = salted-v1
RESULT retention store: body bytes in the store file = 1
RESULT retention store: reconcile before purge ok = True
RESULT retention store: purge without the admin token status 401
RESULT retention store: purge status 200 | store_status purged
RESULT retention store: body bytes in the store file after purge = 0
RESULT retention store: attestation appended = PURGE
RESULT retention store: reconcile after purge ok = True
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.policy_factory", "message": "Using regex policy engine (CUSTOS_POLICY_ENGINE=regex)"}
RESULT split restore: /v1/audit/verify = {'valid': True, 'reason': 'OK', 'chain_length': 2, 'tenant_id': 'default', 'backend': 'SQLiteBackend'}
RESULT split restore: status ok = False | findings ['unattested-purge']
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.shutdown"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.policy_factory", "message": "Using regex policy engine (CUSTOS_POLICY_ENGINE=regex)"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.topology", "replica_count": 1, "rate_limit_store": "process", "audit_backend": "SQLiteBackend", "shared_state_enforced": true, "audit_durability": "durable"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.audit_persistence", "audit_backend": "SQLiteBackend", "audit_durable": true, "audit_store_source": "AUDIT_DB_PATH", "environment": "development", "audit_durability_note": "records survive this process; per-tenant scoping keeps each tenant's chain separate"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.content_retention", "content_retention": "store", "content_store_dir": "/tmp/drill-retention-8gklkk7b/content-gate", "retention_admin_configured": true, "environment": "development"}
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.startup", "version": "1.4.0"}
{"otel.span": {"trace_id": "5f1a341249db4e51ba348fe74f7a6b03", "span_id": "eeaa455241024fe7", "name": "custos.evaluate_action", "start_time": 1794018882.3269167, "end_time": 1794018882.3293247, "duration_ms": 2.41, "status": "OK", "attributes": {"client_id": "drill", "tenant_id": "default", "tool": "payment_transfer"}}}
RESULT action gate: evaluate_action status 200 | allowed True
RESULT action gate: record commitment = salted-v1
RESULT action gate: command bytes in the store file = 1
RESULT action gate: reconcile before purge ok = True
RESULT action gate: purge status 200 | store_status purged
RESULT action gate: command bytes after purge = 0
RESULT action gate: reconcile after purge ok = True
{"timestamp": "2026-11-07T02:34:42Z", "level": "warning", "logger": "custos.retention", "message": "custos.content_retention.purged_content_resubmitted", "tenant_id": "default", "content_hash": "351237ce1854cca796b6a0cd55f5fa0cb21774ea242b7b6f1289eb2624036c7c", "consequence": "decided and recorded with commitment none; the store will not re-hold content a purge removed, and the prior attestation stands"}
{"otel.span": {"trace_id": "a16c8f0074da41a2ad0b1b5d6d84a8d4", "span_id": "595e6867ad0d48b1", "name": "custos.evaluate_action", "start_time": 1794018882.3400443, "end_time": 1794018882.3411226, "duration_ms": 1.08, "status": "OK", "attributes": {"client_id": "drill", "tenant_id": "default", "tool": "payment_transfer"}}}
RESULT action gate: after the purge allowed = True | record commitment = none
{"timestamp": "2026-11-07T02:34:42Z", "level": "info", "logger": "custos.main", "message": "custos.shutdown"}
RESULT off mode records none: True
RESULT off mode refuses the erasure with a reason: True
RESULT store mode records the form the store used: True
RESULT the body is in the store file: True
RESULT the pair reconciles clean before the purge: True
RESULT an unauthenticated erasure is refused: True
RESULT the erasure succeeds: True
RESULT the body is gone from the store file: True
RESULT the attestation is in the chain: True
RESULT the pair reconciles clean after the purge: True
RESULT the split restore is reported by name: True
RESULT the gate allows the registered tool: True
RESULT the gate record names the form the store used: True
RESULT the proposed action is in the store file: True
RESULT the gate pair reconciles clean before the purge: True
RESULT the erasure reaches the gate's record: True
RESULT the action is gone from the store file: True
RESULT the gate pair reconciles clean after the purge: True
RESULT a purged action is still decided: True
RESULT the purged action's new record says none: True
```
