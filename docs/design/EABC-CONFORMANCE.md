# EABC Conformance Statement — CUSTOS-CORE

**Status:** Partial conformance, declared voluntarily. This document is a self-assessment against
[EABC](https://github.com/omwei-org/omwei-eabc) and is not a certification, an endorsement, or an
independent audit. Where a property is not satisfied, it is named as unsatisfied.

| Field | Value |
| --- | --- |
| Implementation name | CUSTOS-CORE |
| Implementation version | 1.3.3 |
| Supported EABC version | docs/001–docs/004 as published at `omwei-org/omwei-eabc` (retrieved 2026-10-29) |
| Implementation profile | `docs/design/EABC-PROFILE.md` |
| Conformance level claimed | **Level 1 partial / Level 2 partial** (no Level 3 claim: profile is partial by design) |
| Supported optional capabilities | disposition records for every decision; external custody anchoring; pre-registered sabotage verification |
| Known limitations | see "Properties not satisfied" below |

## Property assessment

Verdicts: **satisfied** (property holds and the evidence to check it is published), **partial**
(holds for a restricted scope, stated), **unsatisfied** (does not hold as specified).

| EABC property | Verdict | Basis, and where to check it |
| --- | --- | --- |
| P1 Independent Execution Authority | **partial** | Authority is independent of the *governed agent*: an agent cannot self-authorise, because unregistered tools are denied and the allowlist is held outside the agent's control (`custos/action_gate.py`, deny-by-default at `evaluate_action`). It is **not** independent of the *operator*, who sets policy and operates the gate; the attester and the policy setter are the same trust domain. Constraints for separating them are recorded in `docs/design/policy-commit-citation.md` (R6, R7); that separation is **not implemented**. |
| P2 Complete Mediation | **partial (deployment-dependent)** | Every action evaluated by `ActionGate.evaluate_action` is mediated, and an unconfigured tenant denies all tools. Complete mediation is a property of the *deployment topology*, not of the gate: CUSTOS-CORE cannot prove from inside that no unmediated path to an effect exists. Evidence offered is mediation identifiers and decision records, not proof of totality. |
| P3 Deterministic Commit Semantics | **partial** | Decision outcomes are deterministic and recorded (allow or deny, with `triggered_rule` and `reason`). **Missing:** post-execution outcome and terminal execution status are not written to the audit chain, so the record shows what was authorised and decided, not what the executor subsequently did. |
| P4 Context Binding | **partial** | Payload binding exists via `content_hash` in the integrity preimage. **Missing:** no per-action authority credential, no validity interval, no workload identity binding. Scope is bound at rule level (tenant, tool allowlist), not object level. |
| P5 State Binding | **satisfied (restricted)** | Every record cites the sha256 digest of the in-force policy set at emission (`custos/policy_citation.py`; `policy_digest` is inside the `record_hash` preimage). Demonstrated by pre-registered sabotage class `005-weaken-citation`: run [40512412014](https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/40512412014) went red on exactly the two assertions specified in advance. **Not covered:** external system state hash, configuration version, delegated-authority version. |
| P6 Evidence Integrity | **satisfied (conditional)** | `record_hash` is a sha256 over a fixed field set including `previous_hash`, producing a verifiable chain (`AuditLog.verify`). External anchoring to append-only sinks is implemented in `custos/custody.py` — **fail-visible, not fail-blocking, and disabled by default** (`CUSTOS_CUSTODY_ENABLED`). The integrity claim therefore holds only when custody is enabled; with it off, integrity is local to the store. |
| P7 Evidence Correlation | **satisfied for records at binding_version ≥ 1** | Chain and request correlation are inside the preimage: `previous_hash`, `content_hash`, `policy_digest`, `tenant_id`, and since binding version 1 `trace_id` plus a bound `binding` marker that stops a record being relabelled as legacy. Preimage is defined once and shared by the chain verifier and the external custody re-walk (`docs/design/eabc-trace-binding.md`, #72). **Limitation:** records emitted before binding version 1 keep their historical unbound preimage; their `trace_id` cannot be retroactively protected. |
| P8 Failure Semantics | **partial** | Fail-closed on the decision path: unknown or unconfigured tenant denies, and missing evidence is never read as success. **Missing:** explicit terminal execution states (timeout, partial effect, rollback) are not represented in the record. |

## Evidence to check

* Pre-registered designs: `docs/red-proof-records/sabotage-003/DESIGN.md`, `sabotage-custody/DESIGN.md`, `sabotage-citation/DESIGN.md`
* Frozen runs and manifests: `docs/red-proof-records/run-38446904362`, `run-38610363998`, `run-38811246068`, `run-40426037722`, `run-40512412014`
* Custody attack observations: `run-40426037722/custody-attacks/001-rewrite-backend`, `002-truncate-tail`, `003-suppress-anchor`
* Independent reconstruction of run 11 and run 12 by a third party, published with attribution: `github.com/factnotebook/public-reconstructions` (FN-CUSTOS-003 `FN-da06acd59938f5b9`, FN-CUSTOS-004 `FN-b67b3d8fadbb891b`). That reconstruction is factual verification of the preserved records only; its authors state it is not a certification or endorsement, and it does not extend to this document's EABC claims.

## What would move each verdict

| Property | Required work |
| --- | --- |
| P1 | Attester separation per R6/R7: the party that attests the record must not be the party that holds the policy it cites. |
| P2 | Deployment attestation covering all effect-producing paths, plus a bypass-detection test that must go red. |
| P3 | A post-execution disposition record bound to the decision record hash. |
| P4 | Single-use, payload-bound, time-bounded authority credential per action. |
| P7 | Move `trace_id` inside the preimage (requires a versioned record schema and a documented migration, since legacy records must continue to verify). |
| P8 | Explicit terminal execution states in the record schema. |

Maintained by the CUSTOS-CORE maintainer. Corrections welcome as issues or PRs; a claim here that
the artifacts do not support should be treated as a defect in this document.
