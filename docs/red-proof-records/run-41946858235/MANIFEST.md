# Frozen Observation Set — Run 41946858235, Class `011-fabricate-citation`

**Purpose.** A permanent, in-repo copy of the CI evidence artifacts produced by workflow
`ci-red-proof` run 41946858235 (workflow_dispatch, 2026-11-05 01:12 UTC, commit `5aa9762`,
branch `exp/011-fabricate-citation`). GitHub expires run artifacts after ~90 days; this copy makes
the observation set citable indefinitely. The files are byte-identical to the artifacts published on
the run page, and every SHA-256 below matches the hash asserted inside `red-proof-evidence.json`.

**Source (public):** https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/41946858235
**Job:** `Sabotage 011-fabricate-citation must turn tests RED` — success

**Pre-registration.** `docs/red-proof-records/sabotage-fabricated-citation/DESIGN.md`, digest
`2707ea7b569e80b7681430998da6737d467af29787ad6840f7df9d523d760d52`, pinned in
`.github/workflows/ci-red-proof.yml` and verified with `sha256sum -c` before the class ran. The
expected failure set was fixed before this execution and was not edited afterwards.

**Superseded attempt.** This is the second dispatch of the class. The first, run 41946319256, is
retained at `docs/red-proof-records/run-41946319256/` and is not the finding: it reported seven
failures against six pre-registered ones, and the seventh was a documentation-truth guard firing on
the phrase "Class 005 tests whether…" in `docs/design/policy-commit-citation.md`, which matches that
guard's test-count pattern. The prose was reworded in commit `5aa9762`; the design, the prediction
and the pin digest were not touched, and the sealed injection diff (`2eafacf7…`) is identical across
both runs, which is the checkable evidence that the same sabotage produced both observations.

## Verdict

**RED-CONFIRMED, exactly as pre-registered.**

| Pre-registered requirement | Observed |
|---|---|
| Suite must go RED | exit code `1` — RED |
| Exactly six failing assertions | `junit_failures: 6` |
| The failing assertions must be the six named ones | all six, listed below |
| Predicted non-failures must stay green | all passed |

Failure set from JUnit, verbatim class names:

1. `tests.test_action_gate_engine_matrix.TestCitationCoversWhatItCites::test_opa_without_pin_cites_nothing`
2. `tests.test_action_gate_engine_matrix.TestCitationCoversWhatItCites::test_hybrid_without_pin_cites_nothing`
3. `tests.test_action_gate_engine_matrix.TestCitationCoversWhatItCites::test_malformed_pin_is_refused_not_hashed`
4. `tests.test_action_gate_engine_matrix.TestCitationCoversWhatItCites::test_engine_digest_helper_refuses_unpinned_non_regex`
5. `tests.test_action_gate_engine_matrix.TestRecordCarriesTheCitationItClaims::test_opa_record_emits_no_citation_when_unpinned`
6. `tests.test_action_gate_engine_matrix.TestRequireBoundStillGovernsUncitableEngines::test_uncitable_allow_does_not_stand_under_require_bound`

Counts from the run: `6 failed, 746 passed, 37 skipped` (789 collected). The skip count is higher
than a local run because CI lacks the optional OPA and TSA services.

## The weakening

One hunk in `custos/policy_citation.py`: the two-line guard in `engine_policy_digest()` that returns
`None` when a non-regex engine has no policy digest pin is deleted. With it gone, an unpinned OPA or
hybrid engine gets `sha256` over the rules this process can see, and the record cites it as if it
covered the decision. `red-proof-injection-diff.patch`, sealed contemporaneously, is the diff a
reviewer can read.

## Contents

| File | SHA-256 |
|---|---|
| `red-proof-evidence.json` | `5720caf364e1e9fcbf82b92768cc1a529ff1da72799c9f2e9928ab34f740d4f8` |
| `red-proof-junit.xml` | `ce57d109a16d8634f230fde9ee32532f1f68a4c18bf4017fa5c055fc92e8eb43` |
| `red-proof-pytest-output.txt` | `e0d904fd8cf85e51b492374fb85a22ffe548359af5ae5897d6c33d11db07d333` |
| `red-proof-injection-diff.patch` | `2eafacf7de66d5c6b9c32da6d953404361580150e2e77b24c4980bd6962b74de` |
| `red-proof-exit-code.txt` | `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865` |

## Re-verification

From the repository root:

```
cd docs/red-proof-records/run-41946858235/011-fabricate-citation
sha256sum -c <<'EOF'
5720caf364e1e9fcbf82b92768cc1a529ff1da72799c9f2e9928ab34f740d4f8  red-proof-evidence.json
ce57d109a16d8634f230fde9ee32532f1f68a4c18bf4017fa5c055fc92e8eb43  red-proof-junit.xml
e0d904fd8cf85e51b492374fb85a22ffe548359af5ae5897d6c33d11db07d333  red-proof-pytest-output.txt
2eafacf7de66d5c6b9c32da6d953404361580150e2e77b24c4980bd6962b74de  red-proof-injection-diff.patch
4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865  red-proof-exit-code.txt
EOF
```

`red-proof-exit-code.txt` contains `1` and nothing else. The integer is written by the shell before
the record is generated, so it is observable through a channel independent of the record asserting it.
