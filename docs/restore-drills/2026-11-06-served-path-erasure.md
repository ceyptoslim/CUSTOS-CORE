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
- It does not cover `/v1/evaluate_action`, which records `commitment: none` and
  stores no body. That gap is named in `docs/design/content-retention.md` rather
  than left for a reader to infer from a green run.
- It does not measure behaviour under concurrent writers or across replicas. The
  served path is single-replica by configuration, and the refusal for that is a
  separate guard.

## Transcript

```
work directory: /tmp/drill-retention-7b91_0sy
RESULT retention off: /v1/info content_retention = off
RESULT retention off: evaluate status 200
RESULT retention off: record commitment = none | binding_version 2
RESULT retention off: erasure request status 503
RESULT retention off: erasure refusal names the mode = True
RESULT retention store: /v1/info content_retention = store
RESULT retention store: record commitment = salted-v1
RESULT retention store: body bytes in the store file = 1
RESULT retention store: reconcile before purge ok = True
RESULT retention store: purge without the admin token status 401
RESULT retention store: purge status 200 | store_status purged
RESULT retention store: body bytes in the store file after purge = 0
RESULT retention store: attestation appended = PURGE
RESULT retention store: reconcile after purge ok = True
RESULT split restore: /v1/audit/verify = {'valid': True, 'reason': 'OK', 'chain_length': 2, 'tenant_id': 'default', 'backend': 'SQLiteBackend'}
RESULT split restore: status ok = False | findings ['unattested-purge']
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
```
