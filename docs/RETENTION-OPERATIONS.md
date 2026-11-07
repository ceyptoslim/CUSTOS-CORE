# Retention configuration: a runbook for the refusals and the rollback

**Scope:** the two variables that decide whether the served path keeps the content
it reads, the five ways a startup refuses them, and what an operator has to do in
each case. Written for the person meeting one of these at 02:00 during a rollback,
not for a reader studying the design. The design record is
`docs/design/content-retention.md`; this file is the part you act on.

## The variables

| variable | values | what it decides |
|---|---|---|
| `CUSTOS_CONTENT_RETENTION` | `off` (default), `store` | whether the served path keeps the evaluated body |
| `CUSTOS_CONTENT_STORE_DIR` | a directory that already exists | where each tenant's content store file lives |
| `CUSTOS_RETENTION_ADMIN_TOKEN` | an operator secret | the `X-CUSTOS-Retention-Token` every erasure call must carry |

## The five refusals

Startup refuses each of these instead of resolving it to a default. The message
is the whole diagnosis, so it is quoted here to be matched rather than
paraphrased. Four configurations, five messages: `off` with a leftover store and
`off` with a leftover token are separate checks with separate advice.

| configuration | message names | what to do |
|---|---|---|
| mode is not `off` or `store` | `CUSTOS_CONTENT_RETENTION=<value> is not a retention mode` | correct the spelling. There is no third mode and no silent fallback |
| `store` with no `CUSTOS_CONTENT_STORE_DIR` | `requires CUSTOS_CONTENT_STORE_DIR` | set the directory and restart. A retention mode with nowhere to store promises deletion of content it cannot hold. The same missing directory also refuses the request that needed the store, rather than only the boot, because a process that started before the variable was removed would otherwise keep answering |
| `store` with a directory that does not exist | `is not a directory` | **create it yourself**, then restart. It is not created for you: a store path that appears when asked is not one an operator chose |
| `store` with no `CUSTOS_RETENTION_ADMIN_TOKEN` | `requires CUSTOS_RETENTION_ADMIN_TOKEN` | set the token. Content is being kept and nothing can erase it |
| `off` with the directory still set | `is set while CUSTOS_CONTENT_RETENTION=off` | unset it. A configured store the process does not use reads as retention that is on |
| `off` with the token still set | `is set while CUSTOS_CONTENT_RETENTION=off` | unset it. An admin credential with no surface is a credential nobody can reason about. See the rollback below, which is these two cases |

The endpoints refuse separately and at request time, with their own answers: `503`
when retention is off (nothing to act on), `503` when no token is configured (no
administration surface exists), `401` when the header is missing or wrong.

## Rolling back from `store` to `off`

Setting `CUSTOS_CONTENT_RETENTION=off` and nothing else **will not start**. The
store directory and the admin token are still set, and `off` with either one is the
fifth refusal above. This is the cost of refusing to guess, and it meets you during
a rollback, which is why it is here.

The order matters because of what the files are:

1. **Erase what you are obliged to erase first, while the erasure endpoint still
   exists.** With retention on, `POST /v1/retention/purge` per tenant deletes body,
   salt and commitment and appends an attestation the chain can attribute. Once the
   mode is off, that endpoint refuses: there is no longer a surface that knows where
   the files are.
2. **Unset `CUSTOS_RETENTION_ADMIN_TOKEN` and `CUSTOS_CONTENT_STORE_DIR`, and set
   `CUSTOS_CONTENT_RETENTION=off`.** All three in the same change; the process will
   start on the next boot.
3. **Decide what to do with the files that are still on disk.** Nothing in the
   service will touch them again. They are not read, not erased, and not
   referenced by any record: they are simply left. Deleting them by hand is a
   deletion with no attestation, so an auditor reading the chain afterwards sees
   records that say `salted-v1` about content no store holds. That is the
   `body-missing` finding `GET /v1/retention/status` reports, and after a rollback
   it is expected rather than alarming.

The reason step 1 comes first: `off` is a statement that the service keeps nothing
and therefore erases nothing. Making it true requires the erasure to have happened
before the statement, not after.

## Verifying a configuration change

Three checks, in the order that catches the most common mistake first.

```
# 1. what the process says it is doing, not what the environment says
curl -s localhost:8000/v1/info | python3 -c "import json,sys; print(json.load(sys.stdin)['content_retention'])"

# 2. whether the record side and the store side agree
curl -s -H "Authorization: Bearer $CUSTOS_TOKEN" localhost:8000/v1/retention/status

# 3. and for the whole chain, what it has always said
curl -s -H "Authorization: Bearer $CUSTOS_TOKEN" localhost:8000/v1/audit/verify
```

`/v1/info` answers the mode directly so a reader does not have to infer it from
which variables happen to be set. `/v1/retention/status` answering `ok: false` with
`unattested-purge` after a rollback is the expected shape, not a fault.

## What the token is, and rotating it

`CUSTOS_RETENTION_ADMIN_TOKEN` is a second credential, not a second account. It is
sent as `X-CUSTOS-Retention-Token` alongside the ordinary bearer token, because the
bearer token names a client the gate decides for and a deletion is an act by the
operator. Rotation is a variable change and a restart; there is no storage of it
anywhere in the service.

## What an erasure does not do

- It does not reach a copy of the store taken before it. Backup retention is the
  operator's deletion policy, and the per-store recovery windows are in
  `docs/restore-drills/2026-11-06-export-backup.md`.
- It does not touch another tenant's copy of the same body. Each tenant's store is
  its own file, so the same bytes held for two tenants are stored twice and one
  purge reaches one of them.
- It does not make `verify()` say anything about content. That is `reconcile()` and
  `GET /v1/retention/status`, which is a different call making a different claim.
