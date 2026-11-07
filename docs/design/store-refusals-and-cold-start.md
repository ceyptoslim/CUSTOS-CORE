# A full store is a refusal, and two cold starts must not race

Two defects found by the item 1 drill and carried in its transcript as open defects
rather than assumptions. Both are about a condition the service already handled
correctly and reported badly.

## A full store reached the caller as a 500 (issue 130)

What was already right: when the store fills mid-append, the in-memory chain does not
advance past what the store accepted, so there is no record the service believed in
and the store does not hold, and the next request is refused rather than served
unrecorded. What was wrong was the shape of the failure the caller saw. `ENOSPC`
arrived as an unhandled 500, indistinguishable from a bug in the gate and an
invitation to retry something that will not succeed.

`custos/audit.py` now classifies a full store in both backends and raises
`AuditStoreFull`, symmetric with the existing `ChainForkError` classification. One
exception handler on the app turns it into a 503 with:

- `Retry-After: 30`, because the drill showed the service resumes from the last
  durable head when space returns. It is a hint, not a promise: space returning is an
  operator action.
- `X-CUSTOS-Refusal: audit-store-full` and `reason: audit_store_full`, so a caller can
  branch on the condition without parsing prose.

503 rather than 507 because the condition is temporary by construction in the only
run we have measured. The recognition is deliberately narrow: SQLSTATE 53100 and
53200, and the full-store text of the engines this build uses. A storage failure it
does not recognise stays a 500, because guessing that an unknown error is a full store
tells a caller to wait for a condition that may never clear. Recognising too little is
recoverable; recognising too much is not.

The test derives the condition from the store: `PRAGMA max_page_count` is applied to
every connection, so the store genuinely cannot allocate, and the append that follows
is SQLite's own `database or disk is full`. No exception the code must catch is
invented by the test. A small record can still fit in the bytes left in a capped
store, which is a coincidence of page layout rather than a property, so the test
appends a large one.

## Two cold starts raced in schema creation (issue 131)

Both processes saw no table, both created the composite type, and the loser died on
`pg_type_typname_nsp_index` before any guard could refuse it. That is upstream of the
chain: the second process never reached the fork guard. It also means "one replica" is
protecting more than chain state, and a rollout replacing a pod while another boots
could hit it on an empty database.

Both Postgres schema bootstraps (`custos/audit.py` and `custos/policy_store.py`) now
take `pg_advisory_xact_lock` before their DDL. The lock is transaction-scoped, so it
releases when the schema block commits and a failure cannot leave it held. The key is
derived with `schema_lock_key()` from a namespace string rather than chosen, so two
deployments agree without coordination and two different schemas do not block each
other.

The concurrency test runs two threads against a store that reproduces the race
mechanism: the unguarded path lets both threads reach the DDL and raises the
duplicate-type error for the loser, while the locked path serialises and the second
thread finds the table already there. This shows the lock is taken before the DDL and
that two booting processes both come up. It models the race rather than observing one,
because a suite that skips without a database would leave the defect unguarded in
every environment that lacks one.

The modelled test is not the only evidence. `scripts/drills/phase13_cold_start_race.py`
stages the real condition: two OS processes, one empty database, both released at the
same wall-clock instant, repeated for five trials. On `main` at `40d6519` all five
trials have both processes reach the end of schema creation and exactly one append
land, the other refused at the store with `ChainForkError`. The same driver against
the build before the lock, `58c7462`, fails all five trials at schema creation with
the error this issue was filed for, which is the mutation check for the fix rather
than for the unit test.

    RESULT trial 1: schema up 2/2 | appends allowed 1 | refused with ChainForkError 1
    ...

    # the same driver, one commit earlier
    RESULT trial 1: schema up 1/2 | appends allowed 1 | refused with ChainForkError 0
    RESULT trial 1: SCHEMA died UniqueViolation: duplicate key value violates unique
      constraint "pg_type_typname_nsp_index"

It requires a real server and refuses without one, because the error is raised by the
PostgreSQL catalogs and no store this repository can fake will raise it. The limit
that remains: the measurement is of two processes on one host against a local server,
not of a rolling replacement in a cluster with connection pooling in front of it.

## What these do not cover

- A storage failure this build does not recognise is still a 500.
- The two schemas serialise separately, so an audit boot and a policy boot in one
  process take two locks rather than one.
- Advisory locks do not survive a database that refuses the connection in the first
  place, so a boot against an unreachable database still fails at connect.
- A full content store on the retention path is a separate store with its own
  failure shape, and is not covered here.

## Evidence

Tests in `tests/test_store_refusals.py` (11 cases). Mutation checked: removing the
full-store classification fails the two full-store tests and nothing else; removing
the advisory lock fails the two concurrency tests and nothing else.
