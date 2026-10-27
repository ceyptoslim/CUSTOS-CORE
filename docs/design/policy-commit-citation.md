# Policy-Commit Citation at Emission

**Status:** Design (pre-implementation)
**Provenance of the requirement:** peer technical exchange, October 2026. The
critique: an externally-anchored, hash-chained audit log proves the record
was not rewritten after the fact — but it does not prove the enforced
decision cites the *committed object* a monitor's proofs are about. The
runtime record says which rule fired; nothing at emission binds that rule to
a digest of the in-force policy set that an independent party holds a
commitment to. Two assertions — "the monitor proved things about policy P"
and "the gate enforced under P" — currently reconcile only by trusting the
operator. The gap has a name: *declared-before versus observed-at-runtime*.

The custody arc closed the rewrite vector (a consistently rewritten store
is caught by external anchors). This design closes the **provenance vector**:
every emitted record cites the digest of the exact in-force policy set it was
enforced against, and policy commits are anchored to the same custody sinks
as chain heads, so a third party reconciles the record and the commitment in
one step — comparing a cited digest against a proven commitment, never
reconciling two separate assertions.

## Requirements

**R1 — Canonical policy serialization.** The per-tenant in-force policy set
has exactly one canonical byte representation: rules serialized with sorted
keys, sorted deterministically (by rule identifier, then full serialized
form), UTF-8, `json.dumps(..., sort_keys=True, separators=(",", ":"))`. The
`policy_digest` of a tenant is `sha256(canonical_bytes)`. Equal policy sets
must produce equal digests on every platform; any mutation that changes
enforcement semantics must change the digest.

**R2 — Citation at emission, covered by the record hash.** `AuditRecord`
gains a `policy_digest` field. It is read from the same `PolicyStore` object
consulted for enforcement, at decision time, on the same code path that
emits the record — one measured operation, not two reconciled ones. The
digest is included in the `record_hash` preimage. Preimage change is
backward-compatible: the preimage is extended with the field value (empty
for records emitted before this design), so existing persisted chains
continue to verify byte-identically.

**R3 — Policy commits anchored to the custody sinks.** When a tenant's
policy digest changes (on `save_rules`/`delete_tenant`), the canonical policy
commit — `{tenant_id, digest, canonical_json, committed_at_utc}` — is
written to the same `GitAnchorSink` / `TSAAnchorSink` machinery that anchors
chain heads. The system appends; it can never rewrite. Anchoring is
asynchronous and fail-visible: a sink outage never blocks enforcement, it
surfaces through the existing readiness/metrics surfaces.

**R4 — External re-walk with membership semantics.** `verify_custody()`
extends to policy commits: (a) each anchored commit's canonical bytes
re-hash to its declared digest; (b) every audit record's `policy_digest`
resolves to a member of the tenant's anchored commit sequence — a record may
legitimately cite an older digest (policy changed mid-stream), but a record
citing a digest that was never anchored is a provenance gap and reports as a
CONTRADICTION when custody is enabled. The re-walk trusts neither the
operator nor the gate: it compares the record's citation against the
externally held commitment.

**R5 — Additive, disabled by default, no hot-path regression.** The digest
is computed on policy mutation and cached; the evaluate path performs one
cached read at emission. No network I/O on the enforcement path. The feature
ships behind the existing `CUSTOS_CUSTODY_ENABLED` flag. The published
latency envelope (1.47 ms p50, committed at `docs/benchmarks/`) must not
regress measurably; the benchmark harness is the check.

## Non-goals

- **Attester separation.** The gate that holds the policy also emits the
  record. Citation closes the provenance gap; separating the attester from
  the policy-setter is a multi-party architecture question that remains
  open and out of scope for this arc.
- **Monitor integration.** What a formation-time monitor (formal proofs,
  compliance dossiers) does with the anchored commits is its own layer.
  This design provides the shared committed object; it does not define the
  monitor's semantics.
- **Policy version history API.** The anchored commit sequence is the
  history; no additional API is promised in this arc.

## Detection boundary and the red-proof class

Per project discipline, the class is pre-registered before the first
official execution: `docs/red-proof-records/sabotage-citation/DESIGN.md`
(frozen pre-registration, hash-pinned in the workflow) defines the known-bad
patch and the exact assertions that must fail:

- Sabotage `005-weaken-citation`: a deliberate weakening of the citation
  binding — the gate stamps a stale snapshot digest (or omits the digest)
  instead of the in-force one.
- The suite must go red, with the pre-registered failing assertion named in
  advance: the record-emitted under a mid-stream policy change must cite the
  new in-force digest, and tampering the digest post-emission must break
  `verify()`.
- Faulty-green position stated in advance: if the suite stays green on the
  weakened citation, that is a faulty-green event — the discipline failed
  and is reported as such.

## Sequence

1. Implementation PR: canonical digest + emission citation (R1, R2), policy
   commit anchoring + extended re-walk (R3, R4), flag + hot-path envelope
   (R5), with the enforcement tests.
2. Pre-registration PR: `sabotage-citation/DESIGN.md` frozen in-repo,
   `005-weaken-citation.sh` + workflow matrix entry, hash-pinned.
3. First official `workflow_dispatch` execution of the class; all classes
   (001–005) and all attacks re-proven in the same run.
4. Observation set frozen as permanent records, same as every prior run.
