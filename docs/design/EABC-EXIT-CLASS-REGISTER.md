# Exit-class register — profile-level statement against EABC v1

**Status:** submitted against EABC v1 as a companion to [`EABC-CONFORMANCE.md`](EABC-CONFORMANCE.md).
Not a normative addition to docs/004, and not a request to change the contract. This is a first
case, offered so the vocabulary can be judged on whether it makes two implementations comparable
before anyone is asked to adopt it.

**The claim under test:** that "how could this claim fail?" is a better unit of comparison than
"how complete is this property?", and that a small closed vocabulary of exit classes makes two
profiles comparable without requiring them to close the same holes the same way.

## Why the register, rather than more prose caveats

EABC v1 grades evidence depth per property: L1 property declared, L2 evidence supplied, L3 profile
supplied. That is the right axis for *how much* support a claim has. It cannot express *what kind*
of hole a partial verdict contains, and it cannot distinguish a property that is closed at one
boundary and open at another.

This profile before the register read: **P1 partial, P2 partial, P3 partial, P4 partial.** Four
properties, four entirely different failures, one repeated word. A reader comparing this profile to
another implementation's profile learns that both are incomplete and nothing else. Two profiles can
both say "partial on P1" while one means "the attester is the policy setter" and the other means
"we have not written the test yet" — and no amount of levels or profiles separates those.

The register makes the hole the unit. Each entry names a way the claim can fail, states whether
that failure is closed, open, or impossible by construction, and binds the statement to an artifact
that would embarrass it if the statement were wrong. Two implementations can then be compared class
by class even when they close different classes, which is the property EABC needs and cannot
currently express.

## Vocabulary

Four classes, closed. An implementation that needs a fifth should propose it to the contract, not
invent it locally — incomparability is cheaper to prevent than to repair.

| Class | The claim it dents |
|---|---|
| `EX-1 suppression` | A decision exists but no durable evidence of it does. |
| `EX-2 substitution` | The effect performed is not the effect the decision governed. |
| `EX-3 attribution` | The party whose evidence is trusted is the party that set the rule. |
| `EX-4 coverage` | An effect-producing path never reaches the decision point. |

Status values, also closed: `demonstrated-closed`, `declared-open`, `out-of-scope-by-construction`.

### EX-1 suppression

**Boundary.** For every decision the gate returns, exactly one audit record was appended before the
result was returned, and the result carries that record's hash (`audit_record_hash`), so the
decision and its evidence are the same object rather than two events that ought to line up.

**Failure mode.** An effect occurs whose decision left no record; or a record is appended and then
lost between the append and durable storage (crash, disk, or a deletion that takes the tail).

**Declared status.** `demonstrated-closed` inside the process; `declared-open` across the storage
boundary. Those are two different claims, and EABC v1 has one word for both.

**Threat model assumed.** Crash and storage failure are in scope. Adversarial deletion of the store
*and* every external anchor is out of scope: that is a question about the sink's trust, not about
this control, and it is answered in [`chain-head-custody.md`](chain-head-custody.md).

**Artifact.** `custos/action_gate.py` returns `ActionGateResult(..., audit_record_hash=...)` on
every path; `docs/red-proof-records/run-40937305618/custody-002-truncate-tail/custody-attack-observation.json`
records attack `002-truncate-tail` returning `P4_store_completeness: CONTRADICTION` with the detail
"store holds 8 records; anchors cover 12 (truncation detected)".

**Falsification condition.** Any code path returning a decision without an `audit_record_hash`, or a
store that loses its tail while reconciliation still reports `ESTABLISHED`. Either one makes the
`demonstrated-closed` half false.

### EX-2 substitution

**Boundary.** `content_hash` binds the canonical parameters of the decided action into the record
preimage, so the record identifies which effect was authorised and the binding cannot be edited
without breaking the chain.

**Failure mode.** The executor performs something other than the authorised effect — different
parameters, different tool, different destination — while the record still attests to the decision.
Nothing in this repository observes execution.

**Declared status.** `declared-open`.

**Threat model assumed.** The executor is assumed honest, and that assumption is precisely what this
class refuses to grant. Recording a decision is not the same as witnessing an effect, and the gap is
not closed by better evidence about the decision.

**Artifact.** `docs/design/EABC-CONFORMANCE.md` P3 row, plus the "What would move each verdict" entry
requiring a post-execution disposition record bound to the decision record's hash.

**Falsification condition.** A chain that verifies while the recorded `content_hash` and the effect
actually performed differ. Today that requires an observer at the executor; none exists here, which
is why the class is open rather than merely untested.

### EX-3 attribution

**Boundary.** Each record cites the sha256 digest of the policy set in force at emission, inside the
preimage, so a reader can tell *which* commitment the decision was made under and cannot rewrite it
afterwards without breaking verification.

**Failure mode.** The citing party is the policy setter. Citations are then accurate and
unpersuasive: the actor that could have rewritten the rule also produced the evidence that it
followed the rule.

**Declared status.** `declared-open`.

**Threat model assumed.** The operator is treated as an adversary. The governed agent is not
included in this class: it has no write path to the policy store or the tool allowlist, which is
P1's agent-side half and is closed.

**Artifact.** `docs/design/EABC-CONFORMANCE.md` P1 row; `docs/design/policy-commit-citation.md`
constraints R6 (citation must bind the same digest the independent monitor's proof binds, not a
policy object name) and R7 (a digest mismatch is a reconciliation failure, never a degradation to
operator trust).

**Falsification condition.** Two parties where the digest cited at emission is not the digest the
independent monitor holds, and reconciliation refuses rather than proceeding. Until an independent
monitor exists to hold the other digest, this declaration cannot be falsified — and that
unfalsifiability is how a reader can tell it is open rather than closed.

### EX-4 coverage

**Boundary.** Inside the artifact, `evaluate_action` is the only authorisation path, and an
unconfigured tenant denies all tools rather than defaulting to allow.

**Failure mode.** An effect-producing path — a new endpoint, a background job, a direct SDK call —
reaches the effect without passing the decision point. Nothing about the gate's correctness helps
here: an unmediated path is invisible to it.

**Declared status.** `demonstrated-closed` for the in-process API surface; `declared-open` at the
deployment boundary.

**Threat model assumed.** The deployer is benign but fallible. The failure modelled is an earnest
addition that forgets to mediate, not an adversary removing the gate.

**Artifact.** `tests/test_action_gate.py` (fail-closed totality, unregistered tenant denies all
tools); sabotage class `003-weaken-action-gate` in
`docs/red-proof-records/sabotage-003/DESIGN.md`, which went red on exactly two assertions in run
[38610363998](https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/38610363998).

**Falsification condition.** Any effect-producing entry point in this repository that does not call
`evaluate_action`. A test can find that one; no test can find the path a deployer adds later, which
is why the deployment half stays open.

## What "out of scope by construction" requires

The label most easily abused, because "we did not test it" and "a test cannot change this" look
identical from the outside. An architectural argument is required, and it has to be a *constraint*,
not a preference.

**Worked example — pre-binding-v1 records.** Records emitted before binding version 1 cannot have
their `trace_id` protected retroactively (`docs/design/eabc-trace-binding.md`).

*Architectural argument:* the preimage is a function of the fields that existed at emission. A
version-0 record's `record_hash` is a fixed historical fact. Adding `trace_id` to it now would change
the hash of every legacy record, which would destroy the property the control exists to provide —
byte-identical verification of historical chains. So the class is closed by a constraint that runs
in the opposite direction from a test: any attempt to close it damages P6 for historical data.

*Falsification condition for the declaration itself:* a technique that binds `trace_id` to a
version-0 record without altering its stored `record_hash`. If one exists, the out-of-scope claim is
wrong rather than merely convenient.

That is the shape required: the closure has to follow from something structural, and the claimant
has to say what would show they were mistaken. Absence of a test is not an argument.

## Checkability

`tests/test_exit_class_register.py` enforces the shape mechanically:

- every class carries all six fields, each non-empty;
- every status is one of the three closed values, or the vocabulary has changed and the test fails;
- every closure claim cites at least one artifact path that exists in the repository;
- every class carries a falsification condition long enough to say something;
- `out-of-scope-by-construction` entries must carry an architectural argument, not just a status.

Prose can hide a missing artifact. A register that fails CI cannot.

## What this register does not establish

The cells do not total. Four classes at mixed status do not sum to "partially conformant"; there is
no arithmetic that converts exit coverage into a level, and this document refuses to invent one.
Comparability is the deliverable. Whether the *sum* of closed classes justifies a conformance level
is a question for the contract, and it is exactly the kind of question a computation would hide.

Maintained by the CUSTOS-CORE maintainer. Corrections welcome as issues or PRs.
