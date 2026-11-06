# Durable audit for more than one tenant

Status: implemented in the chain, the backends, and the served path. A tenant
manager now builds each tenant's chain already scoped and already resolved from
the environment, and production refuses to serve an audit store that cannot
outlive the process. The two properties below are what made the wiring correct
rather than merely present.

## The two facts that shape it

**Every chain starts from the same all-zero `GENESIS_HASH`.** A unique index on
`previous_hash` alone therefore refuses the second tenant's first record, since
that record's predecessor is the same zero string the first tenant's first
record already claimed. Verified with a raw insert before the index changed:
`UNIQUE constraint failed: audit_records.previous_hash`.

**The loader returned every row in the store.** A second `AuditChain` pointed at
a store the first tenant had written to loaded the first tenant's records and
then verified them green, because a consistent chain is a consistent chain
whoever wrote it. That result looks like a verification of one tenant's chain
and is a verification of an interleaved history belonging to nobody in
particular, which makes it the same class of defect as a summary that outruns
its artifact: correct arithmetic, wrong subject.

## What the chain does now

A chain carries a tenant scope. `AuditChain(tenant_id=...)` scopes the backend's
load and the store's uniqueness key, so a scoped chain holds exactly one
tenant's records and verifies exactly that history.

The uniqueness key is `(COALESCE(tenant_id, ''), previous_hash)`. `COALESCE` is
not decoration: SQLite and PostgreSQL both treat NULLs as distinct in a unique
index, so keying on `tenant_id` directly would put every legacy row, which
carries NULL, outside the constraint entirely. The constraint would appear
present in the schema and protect nothing for exactly the records most likely to
be unexamined.

An unscoped open still serves a single-tenant store, which is the legacy and
single-chain case. Opening a store that holds more than one tenant unscoped is
refused with the tenant names and the remedy, because there is no honest single
answer to "verify this" once the store holds two histories.

## What the served path does now

`TenantManager.register` builds `AuditChain(tenant_id=tenant_id)` and nothing
else constructs a chain, so the store comes from one place: `DATABASE_URL` for
PostgreSQL, `AUDIT_DB_PATH` for SQLite, and in-memory only when neither is set.
Before this, no configuration made the API's records durable: the SQLite and
PostgreSQL backends existed and were tested, and the request path could not
reach either, so a restore drill would have demonstrated the library rather than
the service.

A scoped chain also writes its own tenant. `record()` fills the record's
`tenant_id` from the chain's scope, and refuses a record attributed to a
different tenant. The served path never passed `tenant_id`, so without the fill
every tenant would write into one NULL scope; and a per-tenant chain holding
another tenant's record would verify for a tenant whose history it is not.

`/v1/info` reports `audit_durable` beside `audit_backend`, because a backend name
alone does not say whether the records survive.

## The production refusal

`CUSTOS_ENV=production` with an in-memory audit store refuses to start. The
refusal names the backend, the two variables that would fix it, and why it
exists. A production process that serves an audit trail it cannot keep is the
same defect as a document claiming a property its artifact disclaims, one layer
down, and `/v1/info` would report a backend while the records vanished on the
next deploy.

Two reasons, deliberately distinct. When no store is configured, the message
says so and names the variables. When a store *is* configured and the chain in
force is still in-memory, the message says that instead: the configuration was
read at import and the variable set later, so telling the operator to set a
variable they already set would send them to look in the wrong place. An anomaly
that shares its signature with a misconfiguration gets its own reason, which is
the same rule that separates an unknown binding version from tampering.

Non-production keeps the in-memory default. A development process that has to
provision a database to run a test is a process people stop running, and the
topology log line says `audit_durability: ephemeral` rather than leaving it to
be assumed.

## What this does not do

- **It does not defend against a store-privileged writer**, who can rewrite a
  whole chain consistently. Measured: verification passes.
- **It does not make truncation visible.** Measured: a six-record chain
  truncated to four returns `(True, 'OK')`. Both residuals need external head
  anchoring, which is not planned here.
- **It does not survive a lost store.** Durable means the records outlive the
  process, not that they survive a destroyed volume. Export, backup and a
  restore drill against the served path are item 1's remainder and item 3's
  territory.
- **It does not make the store the only writer.** A store-privileged writer can
  still rewrite a chain consistently and verification passes; external head
  anchoring is the missing piece and is not planned here.
- **It does not pin the salt or the commitment marker**, which item 3 adds to
  the emitter. Records written before and after that change will hold different
  kinds of digest, and the marker is what lets a reader tell them apart.

## The tests, and what they are for

`tests/test_audit_tenant_scope.py` covers the dimension the item 5 fork tests
could not: two tenants, one store. Each chain loads only its own records; both
first records claim the same genesis; both chains verify independently; one
tenant writing does not disturb the other; a stale writer within one tenant is
still refused; a raw insert is still refused by the database; the same
predecessor across two tenants is allowed; and an unscoped open of two tenants
is refused rather than interleaved.

Mutation checked both halves: reverting the index to `previous_hash` alone fails
seven cases across the two modules, and restoring the all-rows loader fails
three.

## The wiring found a second defect, unrelated to storage

`/v1/evaluate` returned 500 in production on every request, before this change
and after it, for a reason that has nothing to do with where records are stored:
`bound_evidence_required()` is true in production, and that endpoint passed a
`trace_id` but never a `policy_digest`, so `record()` raised "the preimage would
carry an unbound record". Verified on `main` at `5ed4ade` with a real token, not
inferred. The endpoint now cites `ctx.policy_engine.rules_digest`, the rule set
its own decision consulted, which is narrower than the gate's citation and is
therefore the honest one for this endpoint: the gate also consults a tool
allowlist that `/v1/evaluate` never reads.

Worth stating plainly because it is the pattern in code again: the check worked,
the endpoint was wrong, and nothing served the endpoint in production long
enough for anyone to notice. A restart drill on the served path found it in the
first two requests.

The first version of that fix read `ctx.policy_engine.rules_digest`, which only
the regex engine has: under `CUSTOS_POLICY_ENGINE=hybrid` the endpoint raised
AttributeError, caught by CI rather than by a reader. The fix now reads through
`content_engine_digest`, which takes the engine's shape from `getattr` because
the action gate hit this same trap once already. A hybrid engine with no
`CUSTOS_OPA_POLICY_DIGEST` pin returns `None` rather than a digest over the
local rules alone, which means in production such a tenant cannot bind a record
on this endpoint. That is the honest outcome of consulting a policy the process
does not hold, and it is stated here rather than discovered during a drill.
