# Service level objectives: what is defined, what is measured, and by whom

**Status:** written 2026-11-07. The last open item of the pilot-entry package.

An objective the service cannot produce is a promise with no instrument. This
document keeps the two apart on purpose: every entry says who produces the number,
and an entry with no producer is labelled DEFINE ONLY rather than dressed as
measured. The pilot is an evidence-gathering exercise, so the deliverable at exit is
a set of transcripts and snapshots, not an average of opinions.

Three markers, used consistently:

- **MEASURED** the service emits it, from `/metrics` or `/ready`, without help.
- **RUN** a drill in `scripts/drills/` reproduces it and exits non-zero if the claim
  is false. It is a fact about a specific commit and date, not a live reading.
- **DEFINE ONLY** a target we hold to operationally, with the producer named as
  someone other than the service. Nothing in this repository can burn the budget,
  because nothing in this repository watches the number.

## 1. What the service emits

`/metrics` is plain text and needs no exporter:

| metric | type | what it counts |
| --- | --- | --- |
| `custos_requests_total` | counter | requests that reached the decision path |
| `custos_requests_allowed` | counter | decisions that allowed |
| `custos_requests_denied` | counter | decisions that denied |
| `custos_requests_audited` | counter | decisions flagged for audit (a subset, not a third outcome) |
| `custos_rate_limit_hits` | counter | refusals by the limiter |
| `custos_audit_chain_length` | gauge | records in the default tenant's chain |
| `custos_tenant_count` | gauge | registered tenants |
| `custos_uptime_seconds` | gauge | seconds since this process started |
| `custos_custody_enabled`, `custos_custody_sink_health`, `custos_custody_anchor_age_seconds` | gauge | chain-head custody, when enabled |

`/ready` reports `policy_engine`, `rate_limiter`, `audit_chain`, `tenant_manager`
and `custody`. The first four gate readiness. Custody reports state and never gates,
which is a deliberate choice recorded in `docs/design/chain-head-custody.md`.

Two things the surface does not have, and both are load-bearing for what follows: a
latency histogram, and any counter that separates refusals by kind. A request
refused before a decision, by the limiter, by authentication, or by a full audit
store, increments `custos_requests_total` and `custos_rate_limit_hits` only in the
third case, so the counters cannot tell an operator which refusal they are looking
at. Issue 158 is that instrument gap.

## 2. Objectives the service measures

**SLO-1, decision accounting is consistent.** MEASURED. Over any window,

    custos_requests_total - (custos_requests_allowed + custos_requests_denied)

equals the requests refused before a decision was reached. This is written as an
inequality with a named difference rather than as a sum, because the difference is
real: a rate-limited request is counted in total and never allowed or denied. The
target is that the difference is fully attributable, which it is not today. That is
the gap in section 1, not a rounding error.

**SLO-2, readiness reflects what the process can actually do.** MEASURED. `/ready`
returns `ready` only when a policy engine holds at least one rule, the audit chain
exists and a tenant is registered. A process that cannot decide refuses readiness
rather than serving untested refusals. A boot refusal is a correct unavailability
and belongs in an incident review as an intended outcome, not as an outage.

**SLO-3, an acknowledged decision is a durable one.** RUN, by
`scripts/drills/phase8_kill_mid_append.py` and `phase10_two_writers.py`. The claim is
narrow on purpose: a decision that returned `200` is in the store before the response
is written, and a second writer against a stale head is refused at the store rather
than forking the chain. Neither drill measures a rate. They measure that the ordering
holds, which is the property an SLO about durability would rest on.

## 3. Objectives that require running an artifact

These have no live metric, so they are facts about a run, not a reading. Each is
reproduced on request and on every change to the subsystem it covers.

| property | artifact | what a failure looks like |
| --- | --- | --- |
| erasure removes body and salt, and the record keeps its integrity | `phase12_served_path_retention.py` (SQLite), `phase14_retention_postgres.py` (PostgreSQL) | reconcile reports a mismatch, or a purged body opens again |
| a split restore is reported rather than verifying green | `phase12`, `phase14` | `retention/status` returns `ok: true` over an `unattested-purge` state |
| a backup taken before an erasure restores content whose commitment reopens | `phase11_export_backup.py` | the restored store is indistinguishable from one that was never purged |
| two processes cold-starting do not race in schema creation | `phase13_cold_start_race.py` | one process dies in DDL with a catalog unique violation |
| a restore works and the schema survives a restart | `docs/restore-drills/2026-11-06-served-path-postgres.md`, phase 6 | the restored chain does not verify against the same digests |

The honest limit of the whole column: these run against one host, one tenant and one
process. A two-replica PostgreSQL deployment keeps one chain and two content stores,
and nothing here speaks to it, because the build refuses two replicas on declaration
in the first place (`docs/design/single-replica-constraint.md`).

## 4. Objectives with no producer in the service

Written down so they are not assumed, and so a pilot report can say which ones stayed
empty.

**Bypass rate. DEFINE ONLY.** The fraction of actions that went around the gate is
only visible to whoever operates the executor. The gate sees what it was shown, so a
budget denominated in bypasses can only come from the party being measured. Asking
this service for the number would produce a number about its own inputs, which is the
error the three-state vocabulary exists to prevent.

**Completeness of the chain. DEFINE ONLY.** `verify()` answers whether the records
link, and a consistent prefix links. Truncation is invisible on reload, which is
stated in `docs/design/audit-single-writer-invariant.md` and is why chain-head custody
exists. Custody measures anchor age and sink health, which catches a stall. It does
not catch a shorter honest-looking chain on its own; that needs an out-of-band
comparison against an earlier anchor, which is an operator procedure, not a metric.

**Correctness of decisions. DEFINE ONLY.** A false allow is a policy defect, and
detecting one needs labelled outcomes from the deployment. The service can report
which rule fired and with what citation; it cannot report that the rule was wrong.

**Erasure completeness across backups. DEFINE ONLY.** A copy of the content store
taken before an erasure restores that content, measured in `phase11`. Whether every
copy is gone is a backup-retention policy question, and the answer lives with whoever
holds the copies.

**Availability across replicas. DEFINE ONLY, and structurally so.** Two replicas are
refused at startup, so there is no failover to measure. An availability objective
over one process would be a claim about a deployment shape this build does not ship.

## 5. Not in this document

No latency objective and no throughput objective. There is no histogram, no load
generator and no measured rate in the repository, and an objective invented in prose
is exactly what a reader would quote back later. When a histogram exists, a latency
objective can be written against it with a stated window and a stated population. Not
before.

## 6. Error budget policy

Budgets attach only to MEASURED objectives, because a budget nothing watches cannot
be spent. For SLO-1 the burn is the unattributable remainder; for SLO-2 it is a
`ready` response from a process that cannot decide; for SLO-3 it is a `200` returned
before the record is durable.

When a budget is exhausted, the policy changes freeze until the drills for the
affected subsystem have been re-run on the current commit and their transcripts
attached to whatever claim is being made. The freeze is the point: an SLO that only
produces dashboards has no effect on behaviour, and this one is small enough that the
only thing it can meaningfully do is stop a release.

## 7. What the pilot hands over

At exit: the drill transcripts with dates and commit SHAs, a `/metrics` snapshot at
the start and the end, the list of objectives that remained DEFINE ONLY, and the
unattributable-remainder arithmetic from SLO-1 for the pilot's window. A negative
result is legible in that set, which is the property that makes the exercise worth
running.
