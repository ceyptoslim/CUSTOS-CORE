# Frozen Observation Set — Run 41768306845, Class `008-weaken-binding-refusal`

**Purpose.** A permanent, in-repo copy of the CI evidence artifacts produced by
workflow `ci-red-proof` run 41768306845 (workflow_dispatch, November 4, 2026, commit
`1521b09d6`, branch `exp/008-binding-refusal`). GitHub expires run artifacts after
~90 days; this copy makes the observation set citable indefinitely. The files are
byte-identical to the artifacts published on the run page, and every SHA-256 below
matches the hash asserted inside `red-proof-evidence.json`.

**Source (public):** https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/41768306845
**Job:** `Sabotage 008-weaken-binding-refusal must turn tests RED` — success

**Pre-registration.** `docs/red-proof-records/sabotage-binding/DESIGN.md`, hash-pinned
in `.github/workflows/ci-red-proof.yml` and verified with `sha256sum -c` before the
class ran. The expected failure set was fixed before this execution.

## Verdict

**RED-CONFIRMED, exactly as pre-registered.**

| Pre-registered requirement | Observed |
|---|---|
| Suite must go RED | exit code `1` — RED |
| Exactly one failing assertion | `junit_failures: 1` |
| The failing assertion must be the named one | `tests/test_startup_binding.py::test_startup_refuses_when_the_binding_cannot_be_written` |
| Predicted non-failures must stay green | 4 of 4 PASS, including the module-level refusal test |

Failure message, verbatim: `DID NOT RAISE <class 'custos.deployment_binding.BindingError'>`
— the process started after a failed binding write, which is the weakened behaviour.

Counts from the run: `1 failed, 729 passed, 37 skipped` (767 collected). The skip
count is higher than a local run because CI lacks the optional OPA/TSA services; the
pre-registration named one expected failure, and the observed set contains exactly one.

## The weakening

One hunk in `main.py`: the lifespan's `except BindingError` handler stops re-raising
and logs a warning instead. `establish()` still raises, `record_binding()` still
raises, `BindingError` still exists — the guarantee survives at the module boundary
and dies at the process boundary. `red-proof-injection-diff.patch`, sealed
contemporaneously, is the diff a reviewer can read.

## Contents

| File | SHA-256 |
|---|---|
| `red-proof-evidence.json` | `4926723691b5aa637e8905f4ed26d319442c34828c0689627d4ae3557e3d949c` |
| `red-proof-junit.xml` | `fb4e9267f87343748d5cc901058a63c8bef733670e55480d8504bbc1a3b4054b` |
| `red-proof-pytest-output.txt` | `b2d971b2f7d54dc00006a8599c9e1e1a7e2a729ec805e226b1d8202cb91b54cf` |
| `red-proof-injection-diff.patch` | `12507bc01ff8860a5775c1fc10dbe3f75a959dff956e7c230a6e04d4cf7fd9e2` |
| `red-proof-exit-code.txt` | `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865` |

Identity sealed in the evidence record: sabotage script
`ef4e7290fba2031946d19103551b590a81299c03c9b5db761908505fa8613171`, injection diff
`12507bc01ff8860a5775c1fc10dbe3f75a959dff956e7c230a6e04d4cf7fd9e2`.

## What this establishes, and what it does not

Establishes: the fail-closed refusal is load-bearing and a test observes it. Removing
one line turns the suite red, and the tripwire names the property rather than the code
shape.

Does not establish: completeness of the binding payload, observation of the credential
on the socket (the fingerprint is declared, not observed), coverage of unmediated paths
(EX-4), or that a human reviewer would notice a fail-open patch in a diff. The blast
radius is one assertion, which the design states in advance: the control is exact and
correspondingly thin.
