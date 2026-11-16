# Evidence Sufficiency for Agent Actions

**Status:** position essay. Written alongside SEP-2848 (Asynchronous Approval for Tool Calls) and first published as a comment in that thread on 2026-11-16.
**Scope:** a case class, a recording rule and a falsifier. The essay makes no claim about any product, including this repository's own.

---

## 1. The question is not "does it verify"

A verifier answers a question that is narrower than the one people ask of it.

"Does this record verify" asks whether a computation over a byte string returns a particular value. "Is this evidence sufficient" asks whether a set of records answers a stated question about a specific action, and what a reader should do when it does not. The second is a relation between a record set and a question, not a property of the record set, and a party who treats the first as a proxy for the second will pass sets that answer nothing.

The failure is not theoretical and it is not exotic. It appears the first time an auditor asks whether the operation was authorized and the system hands back a signature that postdates the operation, or a hash chain that begins after the decision was made.

## 2. The case class: a decision at a boundary

The actions worth recording share a shape. Something was about to happen at a control point, a policy layer reached a verdict, and the action either proceeded or did not. Everything downstream of that boundary is a consequence, and the consequence is often produced by software the gate does not own.

Three questions follow, and they are separately falsifiable:

1. **Route.** Which code path carried the effect, as an artifact of the run rather than a reconstruction afterwards.
2. **Decision.** Whether a decision exists for that exact action, bound to the arguments actually used rather than to a session, a request id, or a timestamp window.
3. **Effect.** Whether anything happened, reported by a reader that is not the actor.

The failure these three are shaped to prevent is a doubled execution behind a single recorded decision. One decision, two effects, and a record set that reads green, because the record describes the decision and never looks at the world.

## 3. The recording rule

Record the three fields independently, and never as a composite that passes when any one of them is internally consistent.

- **Route** is written at the point of effect, not inferred later from a log or a stack trace.
- **Decision** is bound to a digest of the arguments the action actually carried, so it cannot be re-attached to different arguments after the fact.
- **Effect** comes from a reader other than the executor. A system's statement that it did something is a claim about itself, and self-report composes badly with automation because nobody re-checks it.

The two verdicts are not symmetric, and a record format that treats them as though they were will produce confident nonsense.

A **denial** is the easier case: the absence it claims is coupled to the boundary and checkable in the same record set. If the tool was never invoked and the denial is in the chain, the claim is closed.

An **allowance** is harder: the consequence lives downstream, in a system the gate does not own. No amount of care in the gate produces evidence about what the receiving system then did, so the evidence has to come from there, and where no such observer exists the correct verdict is *cannot establish*, not *pass*.

## 4. The falsifier

What a stranger runs, in order, and what each step can fail to establish.

**Step 1, artifact integrity.** Recompute every digest. This is the easy step and the only one a hash chain answers well. It establishes that the bytes are the bytes that were signed, and nothing about whether there should be more of them.

**Step 2, completeness.** Ask whether the set is whole. A hash chain verifies a set as a set, and says nothing about whether that set is the complete one, because a chain whose tail was cut still verifies: nothing inside the store knows how many records ought to exist. This is measured and recorded in this repository, in `docs/design/durable-tenant-audit.md`, where a six-record chain truncated to four returns success, and in `docs/design/chain-head-custody.md`, where the same limit appears in the guarantee table as truncation and deletion being undetectable without external custody.

Alteration and omission are different problems with different fixes. Alteration is answered by any authenticating structure. Omission is answered only by an anchor the writer does not hold: an expected head or next sequence number committed somewhere else, an external counter, or a counterparty who kept a copy. A verifier that only recomputes digests cannot see omission at all, which is why "we keep a signed audit log" is a true sentence that often leaves the question open.

**Step 3, coupling.** For a denial, confirm the absence is at the boundary and inside the same record set, not merely absent from a log. For an allowance, confirm that an observer other than the actor reported the effect. Where no such observer exists, the verdict is *cannot establish*. That verdict is not a failure of the system; it is the honest output of the evidence, and suppressing it is how a record set becomes a reassurance.

**Step 4, coverage.** Compare the routes that produced effects against the declared inventory of routes. An effect observed on a route the inventory does not contain does not falsify that test run. It falsifies the coverage claim itself, which is a larger finding and the one most likely to be discovered by accident.

## 5. What a pass is a statement about

A pass is a statement about the inventory, not about the system. This distinction costs nothing to write down and is expensive to recover later, because a pass reads as a global claim to anyone who did not write the inventory.

The practical form: name what was covered, name what was not, and keep the second list honest as the system changes. An inventory that silently stops being updated converts every subsequent pass into a claim the project cannot support.

## 6. What this essay does not claim

No rates and no proof. The measurements referenced above are observations inside a stated harness, at stated denominators, and one of those harnesses has a documented defect in its own history which this repository publishes rather than quietly reruns.

Re-checking the cited design documents should reproduce the truncation observation. It should not be read as a property of hash chains in general, only as a property of what a verifier choosing to check.

## 7. Provenance

First published as a comment in the SEP-2848 discussion, 2026-11-16:

https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2848#issuecomment-6903646262

The measured case class in this essay was produced by the benchmark series recorded at `docs/benchmark/agentdojo-provenance-record.md`, and the truncation measurement appears in the two design documents named in section 4.
