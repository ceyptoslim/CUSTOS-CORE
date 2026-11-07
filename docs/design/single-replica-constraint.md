# The single-replica constraint, and what scaling would require

Status: item 5 of the pilot-entry package. The constraint is now asserted at
startup instead of being discoverable in the source.

## The conflict this names

Two pieces of state are process-local by default:

* rate-limit counters, held in `RateLimiter` as a dict of per-tenant state with
  a lock around it;
* the audit chain, whose default backend is memory.

Neither is a performance problem. Both are correctness problems the moment a
second process exists. Two replicas hold two independent quota counters, so a
tenant configured at sixty requests per minute gets up to one hundred and twenty
across the fleet, and no single component is wrong about that. Two replicas hold
two chains, so "the" chain is whichever one the load balancer routed the verifier
to, and a chain that verifies says nothing about the records written elsewhere.

The second failure is the worse one for this project specifically, because the
chain is the artifact a customer would point at. A verifier who receives a valid
chain has no way to know a sibling chain exists.

## What the check does

Startup reads `CUSTOS_REPLICA_COUNT` (default 1) and `CUSTOS_RATE_LIMIT_STORE`
(default `process`), compares them with the audit backend actually configured,
and refuses to start when the declaration exceeds the storage. Every conflict is
reported at once rather than one per restart, since an operator fixing a
topology should not discover the second problem after redeploying.

Three refusals:

1. More than one replica with process-local rate limiting.
2. More than one replica with an in-memory audit chain.
3. `CUSTOS_RATE_LIMIT_STORE=external` at all, because this build contains no
   shared store and declaring one would be a claim the code cannot keep. The
   escape hatch is refused rather than wired to a silent downgrade.

A malformed `CUSTOS_REPLICA_COUNT` is also refused. Defaulting a topology to one
when the value cannot be parsed is how a deployment ends up horizontal while
every log line says single.

### Schema creation is inside the declared scope

The three refusals above are stated in terms of chain state and quota counters,
which is how the constraint was first described and is not the whole of what it
covers. A cold start against an empty database creates the audit schema, and two
processes doing that at once race in the catalogs: whichever object one process
creates first, the other fails on a duplicate key. Measured on the pre-lock build
across five trials, the index named in the error was
`pg_class_relname_nsp_index` in three and `pg_type_typname_nsp_index` in two, so
the mechanism is concurrent DDL and the index is an artifact of which statement
each process reached first. Naming one index as the mechanism, as this paragraph
did until the drill was run repeatedly, makes a reader treat the other as a
different fault. That failure happens upstream of the
chain and before the fork guard is reached, so a deployment that would have been
refused for the right reason instead dies for a reason that looks like a
migration fault.

The practical consequence is that the constraint also protects schema creation,
and the case to watch is not a steady state but a rollout: a replacement pod
booting against an empty database while another is still starting is two writers
for the length of that overlap, whichever pid the operator declared. This is
recorded as issue 131. It was a defect rather than a condition, because the correct
behaviour is a named refusal and not a database error surfaced as a crash loop, and
it is fixed: both bootstraps take `pg_advisory_xact_lock` before their DDL, so the
second process waits and then finds the table already there. The fix is measured on a
real server by `scripts/drills/phase13_cold_start_race.py`, two processes released at
the same instant against an empty database, and it fails on the build before the lock.
What this check still cannot do is detect that a rollout overlapped, so the overlap
remains an operator fact rather than something the service reports.

## What the check does not do

It cannot detect how many processes are running. An operator can start three
containers and declare one, and this code will never know. The declaration is
recorded and contestable, which is the same standing as the credential binding
elsewhere in this repository: the process attests to what it was told, not to
what is true on the wire.

It also does not make horizontal scaling safe by being configured. There is no
shared store to configure. The check exists so the gap is stated by the software
rather than discovered by a customer.

## What scaling would require

Three pieces of state have to move together, and moving one is worse than moving
none because it produces a deployment that is half shared:

1. Rate-limit counters in a shared store with atomic increment, so the quota is
   a fact about the tenant rather than about a process.
2. The audit chain on SQLite or PostgreSQL, with the write path serialized
   enough that two processes cannot fork the chain. The persist-before-append
   ordering in the current backend is per process and does not solve this.
3. The idempotency key store from
   `docs/design/idempotent-decision-replay.md`, which has the same shape of
   problem and is documented there for the same reason.

An external limiter at the ingress is a legitimate alternative for the first
item, and worth preferring where it exists, since it moves the quota to the
component that already sees every request. It does not help with the chain.

## How to inspect the claim

Set `CUSTOS_REPLICA_COUNT=2` and start the service. It refuses, and the message
names both conflicting pieces of state. Set it to 1 and it starts, logging
`custos.topology` with the declared count, the store, the audit backend and
whether shared state is being enforced.

Verified locally against this change: the refusal fires for a two-replica
declaration on memory or SQLite, the single-replica path serves `/health`, and
removing the refusal fails five tests including the startup one.

## Two corrections after the constraint shipped

Both were found by exercising this check rather than reading it.

**The memory audit-chain conflict could not fire.** The conflict matched against
`"memory"`, `"inmemory"` and `"in-memory"`. The backend reports
`InMemoryBackend`, so the comparison was always false and the conflict was
unreachable in any real deployment. It was reached only by a test that typed one
of the spellings the check expected, which is a test agreeing with a bug. The
match is now on a normalised name, and the tests take the string from
`AuditChain().backend_type` so they cannot drift from what the backend reports
again.

**Durability is named, not inferred.** The startup line now carries
`audit_durability` and, when the records are ephemeral, a note stating the two
consequences in words: they do not survive a restart, and the `previous_hash`
constraint that prevents a forked chain does not apply, because a constraint on
a store cannot apply where no store is shared. Naming the backend is not the
same as naming the property it lacks, and an operator reading
`InMemoryBackend` should not have to know this codebase to learn that.

What this does not do: it does not refuse an ephemeral backend in production.
The served path builds every tenant's chain with `AuditChain()`, so no
configuration makes the API's records durable today; refusing production until a
durable backend is wired would refuse every production boot of this build. That
refusal belongs in the change that makes durability reachable, not ahead of it.
