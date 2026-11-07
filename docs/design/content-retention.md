# Content retention on the served path

**Status:** implemented, measured by `scripts/drills/phase12_served_path_retention.py`
**Licence:** AGPL-3.0 (public core)

The gate hashed every request into its record and kept nothing. That was
defensible, and it made every statement about erasure on the served path empty:
there was nothing to delete, so there was nothing an erasure request could act
on, and an endpoint to request one did not exist. This note records what was
decided, what each mode claims, and the limits that remain.

## The decision: two modes, neither inferred

| mode | what the service keeps | what a record says | what an erasure request gets |
|---|---|---|---|
| `CUSTOS_CONTENT_RETENTION=off` (default) | nothing | `commitment: none` | refused, naming that there is nothing to act on |
| `CUSTOS_CONTENT_RETENTION=store` | the evaluated body, in a per-tenant side store | the form the store actually used (`salted-v1`) | deletion of body, salt and commitment, plus a `purged-v1` attestation in the chain |

`CUSTOS_CONTENT_STORE_DIR` names the directory, `CUSTOS_RETENTION_ADMIN_TOKEN`
is the operator credential. The mode is read from the environment per call and
named on `/v1/info`, so a reader does not have to infer it from which variables
happen to be set.

Each configuration mistake is refused at startup rather than resolved to a
default, because every default here is a statement about whether the service
keeps the content it reads:

- `store` with no directory: the mode promises an erasure path and has nowhere
  to delete from;
- `store` with a directory that does not exist: refused, not created, because a
  store path that appears when asked is not a path an operator chose;
- `store` with no admin token: content is being kept and nothing can erase it,
  which is the state the mode exists to make impossible;
- `off` with a directory or an admin token set: refused, because a configured
  store the process does not use reads as retention that is on.

This refusal is deliberately unforgiving and has one operational cost: rolling
back from `store` to `off` means unsetting the directory and token too, or the
process will not start. The refusal message names both variables, so it is a
one-line fix, and the alternative is a process that boots looking configured for
retention while recording `none`.

## Tenancy: one file per tenant, and why that differs from the audit store

The audit store is one SQLite file scoped by a `tenant_id` column, because it was
already a single file when cross-tenant uniqueness was fixed. The content store
is a different shape: `content_bodies` is keyed by `content_hash` alone, so
scoping it by tenant would be a schema migration with purge semantics attached.
Instead each tenant's store is its own file inside the configured directory.

Two consequences, stated rather than discovered later:

- the same body submitted by two tenants is stored twice, once per file, and a
  purge of one tenant's copy does not touch the other's. That is the correct
  reading of per-tenant retention: each tenant's erasure is its own;
- a tenant's file appears the first time that tenant evaluates under `store`.
  The directory is operator-chosen; the filename is derived.

The filename is derived for every tenant id the API accepts, hashed
(`content-t-<digest>.sqlite`) when the id cannot name a file. Refusing unusual
ids was tried first and was wrong: `POST /v1/tenants` accepts ids with no
character policy, so a refusal here turns a legal tenant into a 500 on the
decision path. The `t-` prefix is reserved for the hashed form so the two name
forms cannot collide.

## Credentials: two, and why

The retention endpoints sit on the administrative router, which already requires
the standard bearer token, and additionally require
`X-CUSTOS-Retention-Token` to match `CUSTOS_RETENTION_ADMIN_TOKEN`.

The second credential exists because the first does not answer the question the
endpoint asks. A bearer token names a client that the gate decides *for*; a
deletion is an act *by* the operator against stored content, and "any authenticated
client may delete" is not a policy anyone would write. The refusals are distinct:

- retention off: `503`, naming that there is nothing to act on. This is a
  refusal, not a completed deletion;
- no admin token configured: `503`, naming the variable. The administration
  surface does not exist rather than accepting whoever finds it;
- token absent or wrong: `401`.

## The backend the erasure claims were measured on

The retention sequence has been run end to end over HTTP on both backends now:
SQLite by phase 12, and PostgreSQL by phase 14
(`docs/restore-drills/2026-11-07-retention-postgres.md`, 15 checks, all true, on
PostgreSQL 15.19). Both show the same four things: the record names the form the
store used, the purge removes body and salt and appends a `purged-v1` attestation,
the pair reconciles clean on both sides, and a chain restored to before the purge
beside a store past it is reported as `unattested-purge` rather than verifying
green.

This is a statement about the evidence and not about the code. `reconcile()` reads
records through the chain, and the content store is a filesystem side store keyed
by `content_hash`, which does not care which backend wrote the record.

The structural half of that is guarded rather than asserted:
`tests/test_retention_backend_independence.py` fails if either retention module names
an audit backend, a backend class or `DATABASE_URL`. It is a claim about the source
that a reader could not otherwise check from the sentence making it, which is the
shape this document keeps having to correct, and the guard establishes exactly what
the sentence claims: that nothing branches. It is not the measurement.

The measurement was owed anyway, which is the part worth keeping. An argument from
"the code paths are the same" is how the cross-tenant loader and the full-store
refusal were both excused before each turned out to be wrong, and both were found by
running the thing rather than reading it. Issue 149 asked for that run, phase 14 is
it, and it found the behaviour the argument predicted rather than a defect.

## What the served path does and does not cover

Covered: `/v1/evaluate`, including its rate-limited refusal path, which records
`rate_limited` through the same call so a refusal is retained and erasable like a
decision.

Covered: `/v1/evaluate_action`. Until issue 140 this endpoint retained
nothing: the gate wrote its own record with `commitment: none`, which was a true
statement about a gate that stored no body but meant an erasure request could
never reach a decision to run a command. The gate now records through the same
retention-aware path as `/v1/evaluate`, so both endpoints read the form from the
store instead of asserting one, and a purge reaches the gate's records.

**The gate's fail-closed behaviour widened with that change, deliberately.** A
store that cannot accept the body now makes an ALLOW unrecordable, and an
unrecordable allow is a DENY with the reason naming it. The refusal is a
decision, not an exception on the enforcement path: a caller that gets a 500 has
no stated rule to act on.

**Replay records are excluded on purpose.** `POST /v1/replay` binds the content
the caller supplies for verification. Routing it through the store would make a
replay of purged content raise, because the store refuses to re-hold bytes a
purge removed, and replaying a record is exactly the operation that must still
work after an erasure. It records `commitment: none`, which is true of that
record.

## The residual that the write order creates

`put_and_record` stores the body and then writes the record, because the record
must state the form the store used and the only way to know that is to look at
the store. The price is a failure window: if the record write fails, the body can
be left with nothing naming it. It is logged with its digest
(`custos.content_retention.body_without_record`) so it can be purged by hand, and
it is not deleted automatically, because bodies are addressed by content and the
same body may belong to a record written by an earlier request: deleting it to
tidy up this one would destroy that one's content.

Content that was purged and is submitted again is still decided. The store
refuses to keep it again (that refusal is what makes a purge a purge), so the
decision is recorded with `commitment: none` and logged. The alternative, failing
the request, would make an erasure behave like a blacklist.

## What this does not establish

- It does not reach a copy of the store taken before a purge. Backup retention is
  the operator's deletion policy; the recovery windows are measured in
  `docs/restore-drills/2026-11-06-export-backup.md`.
- It does not make `verify()` say anything about content. A chain restored to
  before an erasure, beside a store past it, still verifies `(True, 'OK')`,
  because verification is a statement about record linkage. The disagreement is
  reported by `reconcile()` and by `GET /v1/retention/status`, which is a
  different call making a different claim.
- It does not make the content store's own durability a production guarantee.
  The audit store has a startup refusal for that (`require_durable_audit`); the
  content store is a local SQLite file whose backup story is the operator's.
