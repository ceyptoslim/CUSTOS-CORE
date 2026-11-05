# Frozen Observation Set — Run 41946319256, Class `011-fabricate-citation` (SUPERSEDED)

**Purpose.** A permanent copy of the artifacts from the **first** dispatch of class 011
(workflow_dispatch, 2026-11-05 01:07 UTC, commit `c9af210`, branch `exp/011-fabricate-citation`).
It is retained because it is evidence, not because it is the finding. The verdict for the class is
taken from run 41946858235 (`docs/red-proof-records/run-41946858235/MANIFEST.md`).

**Source (public):** https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/41946319256
**Job:** `Sabotage 011-fabricate-citation must turn tests RED` — success

## Why this run is superseded

Red-CONFIRMED by exit code, but with **seven** failures against six pre-registered ones. The seventh:

```
tests.test_docs_truth::test_no_competing_current_counts_elsewhere
E   AssertionError: Documents state a test count that disagrees with README:
E       docs/design/policy-commit-citation.md: claims 005 (canonical 775)
```

That is a documentation-truth guard matching the phrase **"Class 005 tests whether…"** against its
`(\d{3,5})\s+(?:passed|tests)` count pattern. The sentence was written in commit `c9af210`, in the
same push as the pre-registration, and it was a defect in the prose rather than in the citation
surface: a document that reads as claiming 005 tests pass.

Two things follow, and both are recorded rather than argued away:

- The extra failure was **observed, not pre-registered**, and the design says such failures are
  reported as observed. It is reported here.
- The guard itself was left alone. Loosening the pattern to spare one sentence would weaken a check
  that exists because two documents once contradicted each other.

The prose was reworded in commit `5aa9762` ("Class 005 asks whether…"). No design text, no predicted
failure, and no pin digest changed: the class re-ran against the same `DESIGN.md` digest
`2707ea7b…`. The sealed injection diff is `2eafacf7…` in **both** runs, which is the checkable
evidence that the second run used the same sabotage rather than a softened one.

## What this run still establishes

- The sabotage applied cleanly and the suite went RED with exit code `1`.
- All six pre-registered assertions failed, in this run and in the re-run, with the same messages.
- The remaining predicted non-failures stayed green, including every test in
  `tests/test_policy_citation.py`.

## Contents

| File | SHA-256 |
|---|---|
| `red-proof-evidence.json` | `7b0caec25dcf6c0ca10e34187cbfe4ea8ce85454bf8ed60702a2f56bb6455d8b` |
| `red-proof-junit.xml` | `2424601e6e6a7865f10842c378dde828d5f6db990542d9632e88ec59d030ed66` |
| `red-proof-pytest-output.txt` | `a0a940f72e7c117bb274b031702b1b5512b521f7375aa2ee05c63d522463e3da` |
| `red-proof-injection-diff.patch` | `2eafacf7de66d5c6b9c32da6d953404361580150e2e77b24c4980bd6962b74de` |
| `red-proof-exit-code.txt` | `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865` |

Counts from the run: `7 failed, 745 passed, 37 skipped`.
