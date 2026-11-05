# Sabotage Class `fabricate-citation` — Pre-Registered Experiment Design

**Status:** FROZEN. This file is hash-pinned in `.github/workflows/ci-red-proof.yml` and verified
with `sha256sum -c` before the class runs. It is written before the first execution of the class and
must not be edited afterwards. Corrections belong in a new design, not an edited one.

**Class id:** `011-fabricate-citation`

**Depends on:** the engine-seam fix on `fix/gate-engine-seam` (PR #104). The assertions this class
must trip do not exist on `main` as of `c7fad9d`, so the dispatch ref has to carry that branch. A run
against a tree without them would report FAULTY-GREEN for the wrong reason, which is why the
dependency is stated here rather than discovered later.

## What is under test

One property: **a citation exists only when it covers what the decision consulted.**

`engine_policy_digest()` in `custos/policy_citation.py` computes the digest an audit record cites.
For the regex engine every consulted rule is in the process, so the digest covers the whole of what
the decision read. For the OPA and hybrid engines the Rego rules live in a server this process does
not hold; the only honest citation is the operator's sha256 pin for that bundle
(`CUSTOS_OPA_POLICY_DIGEST`), and when no pin exists there is no digest that covers the decision. The
function returns `None`, and the record carries no citation.

Class `005-weaken-citation` tests a different property through the same module: whether the citation
is *current* (stale cache after a policy change). This class tests whether the citation is *honest*
(a digest that covers the decision versus one that covers the subset the process can see). A
deployment can pass 005 and fail 011, which is exactly the state the fix branch was written against.

## Injected modification class

One change, the minimal natural weakening — the guard that refuses an unhonest digest is deleted:

```python
if engine_kind != REGEX_ENGINE and not opa_policy_digest:
    return None
```

With those two lines gone, `engine_policy_digest()` returns `sha256` over the locally consulted
subset for an unpinned OPA or hybrid engine. The value is a well-formed 64-character hex digest. It
labels itself with the engine kind and carries no pin. A reader of the record cannot tell it apart
from a citation that covers the decision, which is the failure: a record asserting provenance it does
not have is worse than a record asserting none, because the absence is visible and the fabrication is
not.

This is the natural regression rather than a contrived one: the branch is a "make every engine cite
something" change away from shipping, and that change is one reviewer comment ("why is the field
sometimes null?") from being written.

Deliberately *not* weakened: the digest payload, the engine reporting (`engine_kind`,
`citation_rules`, `opa_policy_digest`), the malformed-pin refusal in `opa_engine.py`, the record
write, the `_unrecordable` fail-closed conversion, and the regex path. One vector, so the observed
failure set is interpretable.

## Expected suite outcome (named in advance)

The suite MUST go RED, and the failing assertions MUST be exactly these six:

1. `tests/test_action_gate_engine_matrix.py::TestCitationCoversWhatItCites::test_opa_without_pin_cites_nothing`
2. `tests/test_action_gate_engine_matrix.py::TestCitationCoversWhatItCites::test_hybrid_without_pin_cites_nothing`
3. `tests/test_action_gate_engine_matrix.py::TestCitationCoversWhatItCites::test_malformed_pin_is_refused_not_hashed`
4. `tests/test_action_gate_engine_matrix.py::TestCitationCoversWhatItCites::test_engine_digest_helper_refuses_unpinned_non_regex`
5. `tests/test_action_gate_engine_matrix.py::TestRecordCarriesTheCitationItClaims::test_opa_record_emits_no_citation_when_unpinned`
6. `tests/test_action_gate_engine_matrix.py::TestRequireBoundStillGovernsUncitableEngines::test_uncitable_allow_does_not_stand_under_require_bound`

The sixth is the one that matters commercially. Under `CUSTOS_AUDIT_REQUIRE_BOUND=1` the fabricated
digest satisfies the bound requirement, so an action that should have been refused for having no
citable policy is allowed and recorded as fully cited. Detection by exit code would not distinguish
it from a correct run.

Any additional failure is **observed, not pre-registered**, and is reported as such. A *missing*
failure from this list means the class did not execute as designed and the run is recorded
**FAULTY-GREEN** regardless of exit code.

## Predicted non-failures (stated before the run)

This list is the substance of the design, because it says where the property lives:

- `TestCitationCoversWhatItCites::test_regex_citation_is_unchanged_by_this_fix` — the regex path never
  reaches the guard. If this failed, the sabotage changed something other than the guard.
- `test_opa_with_pin_cites_the_pin`, `test_rotating_the_pin_changes_the_citation`,
  `test_pinned_opa_citation_is_not_the_regex_digest`, `test_hybrid_pinned_differs_from_regex` — a pin
  is present, so the deleted guard was never consulted.
- `TestRecordCarriesTheCitationItClaims::test_regex_record_cites_the_digest` and
  `test_pinned_opa_record_cites_the_pinned_digest` — the record path is untouched.
- `TestRequireBoundStillGovernsUncitableEngines::test_unpinned_opa_denies_and_keeps_its_own_reason` —
  OPA is unreachable in these tests, so the deny happens before any citation is computed. The
  fabricated digest changes what the record says, not the decision, and the assertion is about the
  decision's rule.
- `TestUnrecordableDecisionIsNotAnAllow::test_broken_store_*` — that is the store-failure path
  (`_record` / `_unrecordable`), which this class does not touch.
- Every test in `tests/test_policy_citation.py` — regex-only assertions; the class-005 surface.

## A note on the blast radius

Six assertions out of the suite, all in one file written the same day as the guard they test. That is
the finding rather than a weakness of the pre-registration: the honesty property has exactly one
tripwire, and it lives in the tests that were added with the fix. Nothing in the pre-existing suite
would have noticed a fabricated citation for an uncitable engine, because before the fix an uncitable
engine did not get as far as emitting a record.

## Faulty-green position

If CI reports the suite GREEN under this patch, the finding is: the citation honesty property is
decorative. A deployment on the OPA engine without a pin would emit records claiming policy
provenance it does not have, and under `CUSTOS_AUDIT_REQUIRE_BOUND=1` it would do so while reporting
itself compliant. That outcome is reported as **FAULTY-GREEN**, not as a failed run, and it would
oblige the guard to be re-derived before any further claim about citation honesty is made.

## Blindness — disclosed, weaker than 003 and 006

The same author wrote the guard, the tests, and this design, on the day the class was registered.
There is no blindness claim. What the pre-registration constrains is the interpretation of *this*
run, not the choice of tripwire.

Partial external grounding, stated with its limit: the requirement that an audit citation must not
assert more than the decision consulted was named by an external peer critique of citation practice
(October 2026 exchange, recorded in `docs/design/policy-commit-citation.md`), and the specific
unhonest-engine case was named in the review of the engine seam before the guard existed. The class
tests a requirement that predates its own test. It does not make the test independent of its author.

## What this class does NOT prove

- **That a pin matches the deployed bundle.** A pin is an operator's claim about a server this
  process does not hold. The class proves the process refuses to cite when it cannot cover the
  decision; it proves nothing about whether `CUSTOS_OPA_POLICY_DIGEST` names the Rego actually
  loaded. That gap is a separate claim and stays open.
- **That a reviewer would notice the fabricated digest in a record.** The value is well-formed hex.
  A human reading `policy_digest` cannot tell an honest citation from this one without recomputing it
  against the deployment's pin. CI notices; the human question stays open.
- **That the `_unrecordable` fail-closed conversion is exercised by sabotage.** That property has its
  own assertions and its own store-failure tests, and no class yet makes those assertions fail.
- **Coverage of engines the factory cannot return.** The class tests the three engines that exist.
  A fourth engine added later inherits the obligation and neither the tests nor this class.
