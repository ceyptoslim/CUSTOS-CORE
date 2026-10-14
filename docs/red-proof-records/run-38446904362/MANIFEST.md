# Frozen Observation Set — Run 38446904362

**Purpose.** This directory is a permanent, in-repo copy of the CI
evidence artifacts produced by workflow `ci-red-proof` run 38446904362
(run #9, October 13, 2026, commit `6ed3cff1935f747431aaf58109bf71115f503632`).
GitHub expires run artifacts after ~90 days; this copy makes the
observation set citable indefinitely. The files are byte-identical to
the artifacts published on the run page; every SHA-256 below matches
the hash asserted inside the corresponding evidence record.

**Source (public):** https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/38446904362

**Context.** This is the frozen set used for the first independent
external reconstruction of a CUSTOS-CORE red-proof verdict
(FactNotebook finding FN-CUSTOS-REDPROOF-001, October 2026). The
records here are v2 (pre-upgrade); record spec v3 (full failure set,
sealed injection diff, independent exit-code artifact) followed from
that reconstruction.

## Contents

| Sabotage class | Files | Verdict |
|---|---|---|
| `001-weaken-admin-auth` | evidence JSON, JUnit XML, pytest output | RED-CONFIRMED |
| `002-invert-opa-deny` | evidence JSON, JUnit XML, pytest output | RED-CONFIRMED |

## SHA-256 manifest

### 001-weaken-admin-auth

| File | SHA-256 |
|---|---|
| `001-weaken-admin-auth/red-proof-evidence.json` | `6eee5cd95e3406564fcc7e2ef38673ec145e3b92a8b6cddd25be5082d602759f` |
| `001-weaken-admin-auth/red-proof-junit.xml` | `68086270afd77c8656e5184a931b437d2450870a3a169332f9dbfba023a3b73e` |
| `001-weaken-admin-auth/red-proof-pytest-output.txt` | `45b1c5c36a595c1e12b081c54d85aea56222b45b71c8ace9ad9c3f5eaf0c1dec` |
| `scripts/ci-sabotage/001-weaken-admin-auth.sh` (at 6ed3cff) | `82a0329dacf0c669ef7d28961e331ae2e4044abed9a216c9a570783f03d7d085` |

### 002-invert-opa-deny

| File | SHA-256 |
|---|---|
| `002-invert-opa-deny/red-proof-evidence.json` | `8248908e36a28475b850d8b4053ebfe4aa09275e00e2f0bb9808fdf400686370` |
| `002-invert-opa-deny/red-proof-junit.xml` | `f53c3ea8048d29bb986c73d3f1519ce67f5514f2b9235c95243dfcc87b3f7a99` |
| `002-invert-opa-deny/red-proof-pytest-output.txt` | `59ccd46fd31d58b3b4eac4b4cd0e7bc1788a1cb5ec0a992abfe533ac24df67ed` |
| `scripts/ci-sabotage/002-invert-opa-deny.sh` (at 6ed3cff) | `32a650c3c39773a0d4a875b0bd05195295237f78280996fdfd45002d81a36b2e` |

**Verification rule.** Do not trust this manifest's prose: hash the
files yourself and compare against the hashes asserted inside the
evidence records. The records are the assertion; this directory is the
observation.
