# Class `008-weaken-binding-refusal` — Result of First Execution

**Run:** 41768306845, workflow_dispatch, 2026-11-04, commit `1521b09d6`.
**Design:** `docs/red-proof-records/sabotage-binding/DESIGN.md` (hash-pinned before the run).
**Artifacts:** `docs/red-proof-records/run-41768306845/`.

## Verdict: RED-CONFIRMED, matching the pre-registration exactly

- exit code `1`; JUnit failures `1`; collected `767` (`1 failed, 729 passed, 37 skipped`).
- The single failure is the pre-registered one:
  `tests/test_startup_binding.py::test_startup_refuses_when_the_binding_cannot_be_written`,
  message `DID NOT RAISE <class 'custos.deployment_binding.BindingError'>`.
- All four predicted non-failures passed, including
  `test_a_failed_write_refuses_the_start_rather_than_going_unbound`, which asserts the
  module still raises. That pair is the interesting observation: under the sabotage the
  module refused and the process did not, so the guarantee was intact one layer below
  the layer that mattered.

## Held to the pre-registered reading

Nothing in the observed set required reinterpreting the design, so no correction or new
class is implied. The blast radius came in at one assertion, as stated in advance.

## Standing limits, unchanged by this run

Payload coverage of capability over names, credential observation on the socket,
unmediated paths (EX-4), and human review of a fail-open diff all remain outside this
class. A RED here is evidence about one property, not about the binding as a whole.
