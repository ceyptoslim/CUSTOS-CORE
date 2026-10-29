# EABC Implementation Profile — CUSTOS-CORE

Maps CUSTOS-CORE's internal constructs onto the
[Execution Authority Boundary Contract](https://github.com/omwei-org/omwei-eabc) properties.
Companion to `docs/design/EABC-CONFORMANCE.md`. Implementation version 1.3.3.

## Architectural boundary

```
Agent / caller
    │  proposed action (tool, params, tenant)
    ▼
ActionGate.evaluate_action          ← execution-authority boundary
    │  deny-by-default · allowlist · content rules · fail-closed
    ├──▶ audit record (tamper-evident chain, cites policy digest at emission)
    └──▶ disposition: ALLOW | DENY (+ triggered_rule, reason)
    ▼
Executor (out of CUSTOS-CORE scope)
    │
    ▼
External effect
```

The boundary is one process boundary. Authority direction is one-way: the agent proposes, the gate
disposes. CUSTOS-CORE does not execute effects; it authorises or refuses them and records the
disposition.

## Construct → property mapping

| EABC property | CUSTOS-CORE construct | Where |
| --- | --- | --- |
| P1 Independent Execution Authority | Gate holds the allowlist and policy; agent has no write path to either. Operator remains in the gate's trust domain (declared limitation). | `custos/action_gate.py`, `custos/policy_store.py`, `custos/auth.py` |
| P2 Complete Mediation | `evaluate_action` is the only authorisation path; unconfigured tenant denies all tools. Totality is a deployment property. | `custos/action_gate.py` |
| P3 Deterministic Commit Semantics | Deterministic rule evaluation, DENY takes precedence, no confidence scoring. Decision + reason recorded. Execution outcome not recorded. | `custos/policy_engine.py`, `custos/opa_engine.py` |
| P4 Context Binding | `content_hash` binds the payload; tenant + tool allowlist bind the scope. No per-action credential or validity interval. | `custos/action_gate.py`, `custos/models.py` |
| P5 State Binding | `policy_digest` = sha256 of canonical in-force policy set, computed at emission, inside the record hash. | `custos/policy_citation.py`, `custos/audit.py` |
| P6 Evidence Integrity | `record_hash` chained over `previous_hash`; external anchoring to append-only sinks (git, TSA), fail-visible, opt-in. | `custos/audit.py`, `custos/custody.py` |
| P7 Evidence Correlation | `record_hash` / `previous_hash` / `content_hash` / `policy_digest` / `tenant_id` inside the preimage. `trace_id` present but outside it. | `custos/audit.py` |
| P8 Failure Semantics | Unknown tenant → DENY. Fail-closed on unreachable gate at the executor contract. Terminal execution states absent. | `custos/action_gate.py`, `docs/PRE-FLIGHT-ACTION-GATE.md` |

## Record schema (v1.3.3)

`record_hash = sha256(canonical_json{ timestamp, client_id, action, triggered_rule, reason,
content_hash, previous_hash [, policy_digest] [, tenant_id] })`

Conditional fields are included only when set, so records emitted before citations existed hash
byte-identically to the original preimage and old chains still verify. Field set is taken from
`custos/audit.py::_compute_record_hash`.

## Lifecycle semantics

1. Caller submits an action (tool, parameters, tenant).
2. Gate resolves the in-force policy and computes the policy digest at emission.
3. Rules evaluate; DENY takes precedence over ALLOW.
4. Disposition is returned and an audit record is appended, containing the digest of the policy
   that produced it.
5. If custody is enabled, the record is asynchronously anchored to external append-only sinks;
   failures surface but never block enforcement.
6. Verification (`AuditLog.verify`, `custody.reconcile`) re-walks the chain and compares the local
   chain head against the external anchor log. A mismatch is a contradiction, not a repair.

## Verification artefacts (pre-registered, not retrofitted)

Each sabotage class declares its expected failure mode in a `DESIGN.md` committed before the run,
including the faulty-green position and disclosed blindness:

* `sabotage-003` — action-gate allowlist weakening
* `sabotage-custody` — backend rewrite, tail truncation, anchor suppression
* `sabotage-citation` — citation binding weakening (must fail exactly two named assertions)

Frozen per-run artefacts: `docs/red-proof-records/run-*` (manifest, injection diff, JUnit, exit code,
probe pair where instrumented).

## Unsupported capabilities (explicit)

* Per-action authority credential with scope and validity interval.
* Post-execution outcome attestation.
* Attester separation from the policy-setting operator (R6/R7 recorded in
  `docs/design/policy-commit-citation.md`, not implemented).
* Hardware or TEE-rooted attestation: this profile makes no claim beneath the software boundary.
* Multi-party custody: anchors go to configured sinks, not to a quorum the operator cannot control.
