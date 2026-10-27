# Chain-Head Custody: External Anchoring for the Audit Chain

**Status:** Implemented — `custos/custody.py`, disabled by default. Companion red-proof class `custody`: pre-registered, execution pending.
**Scope:** Deployment-time external custody of audit chain heads. No change to the
decision hot path beyond a head-read under the existing lock.

---

## 1. The problem, stated plainly

The audit chain is tamper-evident, not tamper-proof, and today its evidence lives
entirely inside the system under investigation:

- Records are stored in backends the deployment controls (`InMemory`, `SQLite`, `PostgreSQL`).
- `AuditChain.verify()` re-walks records loaded **from that same backend**. It detects
  inconsistent edits (a rewritten record breaks its `record_hash`), but a writer with
  backend access can rewrite the entire store consistently — every `previous_hash`
  recomputed — and verification passes.
- Truncation and deletion are invisible to the chain itself: a shorter honest-looking
  chain verifies green.

This is the "writer belongs to the system under investigation" boundary already
conceded in the published red-proof record. In the registry context, externalization
came from construction: records were frozen under a third party's repo and re-hashed
by a party outside the system. Deployment needs the equivalent, without a forensic
researcher in the loop.

**Claim made by this design:** chain heads are anchored to external append-only
custody sinks at bounded intervals, such that any rollback, truncation, rewrite,
or deletion of the audit store is detectable by an external party using only
externally held artifacts.

---

## 2. What the chain proves today (and cannot)

| Property | Status today |
|---|---|
| A record has not changed since write | Within the store, until the store is rewritten |
| The chain is internally consistent | Yes — until a consistent rewrite |
| The chain is complete | No — truncation/deletion undetectable |
| Records were accurate at write | No — and not addressed by this design (corroboration remains the answer) |
| Actions outside the gate are covered | No — unchanged; outside the audit surface by construction |

---

## 3. Design goals

- **G1 (External detection):** Any rollback, truncation, rewrite, or deletion of the
  audit store must be detectable by a party outside the deployment using only
  externally held artifacts.
- **G2 (Non-repudiation of heads):** "The chain head was H at time T" must be provable
  from custody the deployment cannot silently rewrite.
- **G3 (Fail-visible, not fail-blocking):** A custody sink outage must never block
  enforcement (availability-first) but must be recorded and surfaced — a visible
  anchoring gap, never a silent one.
- **G4 (Bounded claims):** The design states what it does not establish, in the same
  register as the red-proof record.

---

## 4. Mechanism

### 4.1 Anchor records

A background anchoring task (thread in the API process; the same process boundary as
the rate limiter) reads the current chain head under the existing chain lock and
emits an anchor record:

```json
{
  "tenant_id": "default",
  "epoch": 42,
  "chain_length": 3187,
  "head_hash": "<record_hash of the latest record>",
  "prev_anchor_hash": "<anchor-hash of epoch 41>",
  "anchored_at_utc": "2026-10-27T02:00:00Z",
  "gap": null
}
```

Anchors are themselves hash-chained (`prev_anchor_hash`): reordering, dropping, or
substituting an anchor breaks the anchor chain. `epoch` is monotonically increasing
and never resets.

**Interval:** anchored every `N` records or `T` seconds, whichever comes first
(defaults `N=50`, `T=300`). This bounds the forensic window: at most `N-1` records
can be lost to a store deletion, and the loss is *detectable* as a length
discontinuity against the last anchored length.

### 4.2 Custody sinks (pluggable, phased)

`custos/custody.py` defines a `CustodySink` protocol (`append(anchor) -> sink_ref`,
`healthcheck() -> bool`). Sinks ship in phases:

- **Phase 1a — Git anchor (default sink).** Anchors are committed to an external
  git repository under an account/org **separate from the deployment's infrastructure**,
  on a branch with required branch protection (no force-push, no deletion). This is
  the red-proof pattern generalized to deployment: the system holds append rights,
  not history-rewrite rights. Honest disclosure: an org-admin compromise can bypass
  branch protection; a public mirror narrows this to "detectable collusion," not
  "impossible." Both the limitation and the mitigation are part of the record.
- **Phase 1b — RFC 3161 timestamping.** Each anchor's `head_hash` is additionally
  stamped by an external TSA, giving a third-party signature that a specific head
  existed at a specific time. Independent of git custody entirely.
- **Phase 2 — WORM record store.** The full audit records (not just heads) stream to
  an S3-Object-Lock-compatible bucket in compliance mode. Custody of records, not
  merely of heads. Complements 1a/1b rather than replacing them.
- **Phase 3 — Witness co-signing (research track).** An external witness key
  countersigns heads near-real-time and publishes signed roots. This is the
  transparency-log / key-transparency lineage and is explicitly marked research-grade;
  it is the natural collaboration surface for external forensic review.

### 4.3 Anchor gaps (fail-visible)

If no sink is reachable at an anchor point, the anchor is not dropped silently. The
next successful anchor carries a `gap` object:

```json
{ "gap": { "from_epoch": 42, "attempts": 7, "first_attempt_utc": "...", "last_attempt_utc": "..." } }
```

The `/ready` custody check reports stale anchoring (last anchor older than `2T`),
and `/metrics` exposes `custos_custody_anchor_age_seconds` and
`custos_custody_sink_health`. Enforcement never blocks on a sink.

---

## 5. External verification (`custos.custody.verify`)

A standalone re-walk, runnable by **any third party** with (a) read access to the
external anchor log and (b) a copy of the audit backend:

1. Recompute the full record chain from the backend copy; confirm internal consistency.
2. Reconcile against the anchor chain: at each epoch, the recomputed head at
   `chain_length` must equal `head_hash`; lengths must be strictly monotonic.
3. Verify TSA signatures where present.
4. Emit a verdict per proposition — `ESTABLISHED`, `CANNOT ESTABLISH`, or
   `CONTRADICTION` — in the register of the red-proof record.

This is the artifact answer to the forensic critique: the verification path never
loads evidence from the system under investigation alone.

---

## 6. Threat coverage

| Attack | Detection |
|---|---|
| Rewrite one record in place | Anchor head mismatch (CONTRADICTION) |
| Truncate tail of the store | Length discontinuity vs last anchored length |
| Rewrite entire store consistently (rewrite-and-rehash) | Recomputed head ≠ anchored head |
| Delete store entirely | Anchors survive externally; deletion itself is ESTABLISHED |
| Backend credential compromise | Anchors and TSA stamps held outside the compromise domain |
| Git history rewrite via admin compromise | Branch protection + public mirror; disclosed residual |
| Sink outage | Recorded gap; stale-anchor alert; never silent |

**Not covered (stated, not implied):** actions that never pass through the gate;
accuracy-at-write; completeness of the window between store deletion and the last
anchor (bounded to `N-1` records, and the bound itself is established by the anchors);
TSA key compromise (RFC 3161 policy domain, out of scope).

---

## 7. Red-proof class `custody` (pre-registered)

Same discipline as classes 001–003: `DESIGN.md` frozen in-repo before execution,
`workflow_dispatch` run, records frozen as observation sets.

- **custody-001 — rewrite-backend:** mutate the SQLite audit store in place
  (rewrite a mid-chain record, recompute the whole chain consistently). Expected:
  internal `verify()` green; **external custody verify CONTRADICTION.** This is the
  sharpest possible demonstration of the boundary: the system's own check passes,
  the external anchors catch what it cannot.
- **custody-002 — truncate-tail:** delete the newest K records from the store.
  Expected: length discontinuity reported.
- **custody-003 — suppress-anchor:** simulate sink outage. Expected: gap recorded,
  stale-anchor surfaced, enforcement unaffected (fail-visible, not fail-blocking).

---

## 8. Configuration

| Env | Default | Meaning |
|---|---|---|
| `CUSTOS_CUSTODY_ENABLED` | `false` | Master switch (fail-visible off = explicit, not silent) |
| `CUSTOS_CUSTODY_SINKS` | `git` | Comma list: `git`, `tsa`, `worm` |
| `CUSTOS_CUSTODY_GIT_REPO` | — | External anchor repo (must differ from the deployment org) |
| `CUSTOS_CUSTODY_ANCHOR_N` | `50` | Records per anchor |
| `CUSTOS_CUSTODY_ANCHOR_T` | `300` | Seconds per anchor |
| `CUSTOS_CUSTODY_TSA_URL` | — | RFC 3161 endpoint |

No configuration is required for the existing chain: custody is additive and
disabled-by-default until explicitly deployed.

---

## 9. Boundaries inherited unchanged

This design externalizes custody of what the gate saw. It does not extend what the
gate sees: actions outside the gate remain outside the audit surface, records
remain records of decisions (not proof of content truth), and the chain remains
self-attestation at write time — with corroboration, external re-walkability, and
now external head custody as the answer to each boundary in turn.
