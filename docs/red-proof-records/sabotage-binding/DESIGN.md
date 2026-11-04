# Sabotage Class `binding-refusal` — Pre-Registered Experiment Design

**Status:** FROZEN. This file is hash-pinned in `.github/workflows/ci-red-proof.yml` and verified
with `sha256sum -c` before the class runs. It is written before the first execution of the class and
must not be edited afterwards. Corrections belong in a new design, not an edited one.

**Class id:** `008-weaken-binding-refusal`

## What is under test

The claim, as the inventory states it: a deployment that sets `CUSTOS_DEPLOYMENT_BINDING` either
writes a binding record at startup or refuses to start. There is no third outcome in which a process
runs while `/v1/info` reports `established: true` and no record exists in the store.

The mechanism, in `main.py::lifespan`:

```python
try:
    _startup_binding = establish_startup_binding(
        tenant_manager.get("default").audit_chain,
        policy_digest=action_gate.cited_policy_digest("default"),
    )
except BindingError as exc:
    logger.error("custos.deployment_binding.refused", extra={"reason": str(exc)})
    raise
```

The property lives in the bare `raise`. Everything else in that block is logging.

## Injected modification class

One change, the minimal natural regression: replace the re-raise with a warning and continue. This
is the patch a well-meaning operator writes after a bad deploy — "a metadata write should not take
down the service" — and it is also the patch that converts a fail-closed control into a comment
about one. Note what it does *not* touch: `establish()` still raises, `record_binding()` still
raises, `BindingError` is still defined and still propagates through the module. The guarantee
survives at the module boundary and dies at the process boundary, which is exactly where a reader
would stop checking.

Deliberately *not* weakened: the flag gate, the payload construction, the citation, the record
write itself. One vector, so the observed failure set is interpretable.

## Expected suite outcome (named in advance)

The suite MUST go RED, and the failing assertion MUST be exactly this one:

1. `tests/test_startup_binding.py::test_startup_refuses_when_the_binding_cannot_be_written`

Any additional failure is **observed, not pre-registered**, and is reported as such. A *missing*
failure from this list means the class did not execute as designed and the run is recorded
**FAULTY-GREEN** regardless of exit code.

## Predicted non-failures (stated before the run)

This class is expected to leave these passing, and the list is the substance of the design:

- `test_a_failed_write_refuses_the_start_rather_than_going_unbound` — this asserts that `establish()`
  raises. The sabotage does not touch that function, so the module-level guarantee still holds while
  the process no longer acts on it. If this test failed, the weakening would be somewhere other than
  where this design says it is.
- `test_startup_writes_no_binding_when_the_flag_is_off` — the flag gate is untouched.
- The payload, citation and strict-bound-mode tests — `custos/deployment_binding.py` is untouched.

## A note on the blast radius

This class is expected to trip **one** assertion out of the whole suite. That is not a weakness in
the pre-registration; it is the finding. The fail-closed property rests on a single test, so a single
deletion of one line ends it, and the run exists to record how thin that tripwire is. A class that
failed thirty assertions would say the surface is redundant; this one says it is exact.

## Faulty-green position

If CI reports the suite GREEN under this patch, the finding is: the refusal is decorative. A
deployment could run unbounded while reporting itself bound, and nothing in the suite would notice.
That outcome is reported as **FAULTY-GREEN**, not as a failed run, and it would oblige a follow-up
test before any further claim is made about the binding.

## Blindness — disclosed, weaker than 003 and 006

The same author wrote the wiring (#100), the tests, and this design, on the day the class was
registered. The pre-registration constrains *this* run's interpretation but is not review by someone
who did not write the code. The specific resulting risk here is larger than usual: the expected
failure set and the tripwire were both written by the person who chose where to put the tripwire.

One partial external grounding: the fail-closed requirement was named by a third party before the
implementation existed — the review of #98 asked what happens to a process whose binding cannot be
recorded, and "refuse" was chosen then, not now. The class tests a requirement that predates its own
test.

## What this class does NOT prove

- It does not prove the payload covers capability rather than names; that is the descriptor-digest
  work, covered by unit tests, not by this class.
- It does not prove the recorder observes the credential presented on the socket. It cannot; the
  fingerprint is the value the caller declares. The limit is stated in the module and in the
  inventory, and no sabotage run will remove it.
- It does not prove a reviewer would notice a fail-open patch in a diff. CI notices; the human
  question stays open.
- It does not establish coverage of unmediated paths. A process that never connects to the mediated
  surface writes no binding record, which is a different claim and remains in EX-4.
