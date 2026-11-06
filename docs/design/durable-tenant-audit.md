# Durable audit for more than one tenant

Status: design decision, implemented in the chain and the backends. The served
path is not wired to a durable backend yet; that is the next change, and this
document exists because the wiring cannot land correctly without the two
properties below.

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

## What this does not do

- **It does not make the served path durable.** `TenantManager` still builds
  each tenant's chain with `AuditChain()`. Nothing here changes that, and item
  1's restore drill remains a drill on the library until it does.
- **It does not defend against a store-privileged writer**, who can rewrite a
  whole chain consistently. Measured: verification passes.
- **It does not make truncation visible.** Measured: a six-record chain
  truncated to four returns `(True, 'OK')`. Both residuals need external head
  anchoring, which is not planned here.
- **It does not enforce a tenant on the append path.** A scoped chain loads one
  tenant's records; a caller that writes a record with a different `tenant_id`
  is refused by the store's predecessor key only when that predecessor is
  already claimed. Binding the record's tenant to the chain's scope is the
  wiring change's job, where the tenant is established rather than passed.

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
