# The single-replica constraint, and what scaling would require

Status: implements item 5 of the committee package. The constraint is now
asserted at startup instead of being discoverable in the source.

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
