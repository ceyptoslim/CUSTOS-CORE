# Class `011-fabricate-citation` — Result of First Execution

**Run:** 41946858235, workflow_dispatch, 2026-11-05 01:12 UTC, commit `5aa9762`, branch
`exp/011-fabricate-citation`.
**Design:** `docs/red-proof-records/sabotage-fabricated-citation/DESIGN.md` (digest `2707ea7b…`,
pinned in the workflow before the run).
**Artifacts:** `docs/red-proof-records/run-41946858235/`.
**Superseded first attempt:** `docs/red-proof-records/run-41946319256/` — same sabotage, same sealed
diff, one extra failure that was a documentation guard tripping on the design's own prose.

## Verdict: RED-CONFIRMED, matching the pre-registration exactly

- exit code `1`; JUnit failures `6`; `6 failed, 746 passed, 37 skipped` (789 collected).
- All six pre-registered assertions failed, and nothing else did:

  1. `test_opa_without_pin_cites_nothing` — `assert '90d4f69c…' is None`
  2. `test_hybrid_without_pin_cites_nothing` — `assert '28cd135c…' is None`
  3. `test_malformed_pin_is_refused_not_hashed` — `assert '90d4f69c…' is None`
  4. `test_engine_digest_helper_refuses_unpinned_non_regex` — `assert '289cddc2…' is None`
  5. `test_opa_record_emits_no_citation_when_unpinned` — `assert '90d4f69c…' is None`
  6. `test_uncitable_allow_does_not_stand_under_require_bound`

- Every predicted non-failure passed: the regex byte-compatibility test, all four pinned-engine
  assertions, the two record assertions with a pin present, the unavailable-OPA deny that keeps its
  own rule, the store-failure path, and all of `tests/test_policy_citation.py`.

## What the sixth failure actually shows

The interesting failure is not the five `assert … is None`. Those say a value appeared where the
design says no honest value exists. The sixth says what that is worth commercially.

Under `CUSTOS_AUDIT_REQUIRE_BOUND=1`, an action the engine could not cite should be refused: the
`_unrecordable` conversion turns it into a deny with rule `action_gate_record_unwritable`. With the
fabricated digest, the bound requirement is satisfied, so the action is **allowed and recorded as
fully cited**. The assertion that caught it compares the reason text:

```
AssertionError: assert 'No policy citation' in 'The decision could not be recorded, so the allow does not stand. '
```

Read carefully, that message is the finding: the gate denies for a different reason than the one it
would have given had the citation been absent. A deployment in this state does not merely hold a
false record. It holds a record that says the policy was cited, on an action the policy gate could
not see, and its compliance switch reports success. No exit code and no log line distinguishes that
from a correct run, which is why the class asserts the citation surface directly instead of inferring
it from a verdict.

## The re-run, and why it is disclosed

The first dispatch (run 41946319256) reported seven failures. The extra one was
`tests/test_docs_truth::test_no_competing_current_counts_elsewhere`, failing on the sentence
"Class 005 tests whether the citation is current" in `docs/design/policy-commit-citation.md`, which
the docs guard reads as "005 tests". That is a real defect in prose written in the same push as the
pre-registration, so it was fixed in commit `5aa9762` and the class re-dispatched.

What did **not** change: the design, the six predicted failures, the predicted non-failures, the pin
digest, and the sabotage. The sealed injection diff is `2eafacf7…` in both runs, and every
pre-registered assertion failed identically in both. A re-run after a known result is where
pre-registration usually dies; the check that it did not here is the unchanged diff and the unchanged
digest, both of which a reader can verify from the two manifests rather than take on trust.

## Held to the pre-registered reading

Nothing in the observed set required reinterpreting the design. The blast radius came in at six
assertions in one file, as stated in advance, and the pre-registered non-failures located the
property: the regex path and the pinned-engine path were untouched, so the weakening was where the
design said it was.

## Standing limits, unchanged by this run

- **A pin is an operator's claim.** This run shows the process refuses to cite when it cannot cover
  the decision. It says nothing about whether `CUSTOS_OPA_POLICY_DIGEST` names the Rego bundle the
  server actually loaded. A deployment can pass this class while pinning the wrong bundle.
- **A human cannot see the difference.** The fabricated value is well-formed hex. Noticing requires
  recomputing the digest against the deployment's pin, which a record reviewer does not do by
  reading.
- **The `_unrecordable` fail-closed conversion has no class of its own.** Its assertions were
  exercised here only as collateral of the citation surface. No pre-registered sabotage yet makes the
  store-failure path's assertions fail.
- **Three engines, not all future engines.** A fourth engine inherits the obligation and neither the
  tests nor this class.

A RED here is evidence about one property on one seam, not about citation integrity as a whole.
