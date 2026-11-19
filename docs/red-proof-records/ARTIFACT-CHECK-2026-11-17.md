# Artifact check against the frozen manifests, 17 November 2026

**Purpose.** Record the digest comparison in the repository so the result survives the
artifacts. GitHub expires workflow artifacts roughly 90 days after creation; the frozen
observation sets in this directory do not expire, and this note binds one to the other while
both are still reachable.

## What was compared

Four CI Red-Proof runs (`workflow_dispatch`), each against its own frozen manifest in
`docs/red-proof-records/run-<run_id>/MANIFEST.md`, read at CUSTOS-CORE main `b031fe0`.

| Run id | run_number | Head commit | Uploaded artifact files | Byte-identical, path and hash |
|---|---|---|---|---|
| 38446904362 | 9 | `6ed3cff193` | 6 | 6 |
| 38495005061 | 10 | `925f96eabe` | 10 | 10 |
| 38610363998 | 11 | `f5d48c929e` | 17 | 17 |
| 38811246068 | 12 | `b06098c0bd` | 17 | 17 |

Total: 50 uploaded files, 50 byte-identical to the recorded entry, with the class directory
also matching. No file was matched on digest alone where the filename or class disagreed.

## Method

1. `GET /repos/ceyptoslim/CUSTOS-CORE/actions/runs/{run_id}/artifacts` for each run, to list
   the artifact names, ids, sizes, `created_at` and `expires_at`.
2. `GET /repos/ceyptoslim/CUSTOS-CORE/actions/artifacts/{artifact_id}/zip` with a read token,
   one request per artifact, then extract locally.
3. `sha256` over each extracted file's bytes.
4. Compare against the manifest lines for the same run. Runs 11 and 12 record `sha256sum`
   format lines; runs 9 and 10 record markdown tables.

Two further rows were checked by hand because they are repository files rather than uploaded
artifacts. Run 9's manifest pins the two sabotage scripts at `6ed3cff`; both match the
repository at that commit (`82a0329d…` and `32a650c3…`). Run 12's manifest pins its own
`README.md`, which matches at `168f53f4…`. Run 11's manifest pins its `README.md` at
`fc9d18d8…`, so that file is deliberately left unedited; notes about it belong in
`COUNT-BASIS-506.md`, not inside the frozen set.

Artifact names as uploaded: `red-proof-records-001-weaken-admin-auth`,
`red-proof-records-002-invert-opa-deny`, `red-proof-records-003-weaken-action-gate`, and
`red-proof-probe-003-weaken-action-gate` (two files). Runs 9 and 10 carry the first two only,
with three and five files per class respectively.

## Reproduce it

```
R=38610363998
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.github.com/repos/ceyptoslim/CUSTOS-CORE/actions/runs/$R/artifacts"
# for each artifact id A returned above:
curl -sL -H "Authorization: Bearer $TOKEN" \
  "https://api.github.com/repos/ceyptoslim/CUSTOS-CORE/actions/artifacts/$A/zip" -o "$A.zip"
# then sha256 each extracted file and compare with
# docs/red-proof-records/run-$R/MANIFEST.md
```

## Expiry of the artifacts compared

| Run id | Artifacts expire |
|---|---|
| 38446904362 | 2027-01-11T18:27:34Z |
| 38495005061 | 2027-01-12T01:18:32Z |
| 38610363998 | 2027-01-12T17:52:33Z |
| 38811246068 | 2027-01-13T21:37:11Z |

After those times the manifests and the files in this directory remain, and the uploaded
artifacts do not.

## What this establishes

The bytes GitHub serves for these four runs today are the bytes recorded in the frozen
manifests, so the manifests describe the artifacts they claim to describe, and a reader who
runs the same requests before expiry should obtain the same digests.

## What this does not establish

- **It is a project check, not third-party corroboration.** It was run by the project, about
  the project's own runs. The subject-run limit is unchanged: a repeat by someone outside the
  project would make the claim stronger, and until then `custody_verified` stays False.
- **It says nothing about what executed.** Matching digests show that the uploaded file is the
  recorded file. They do not show which machine ran the job, that the uploaded file is the one
  the runner wrote, or that any artifact was produced without interference.
- **It does not extend to the reconstructions.** FN-CUSTOS-001 through -004 are separate
  documents produced outside this repository; this note concerns the CI artifacts only.

## A note on two figures that read alike

The number 506 appears in two places with different meanings, and the coincidence is
arithmetic rather than evidence:

- In `run-38495005061/MANIFEST.md`, 506 is **collected tests** at `925f96e`: 465 passed,
  6 failed, 35 skipped for class 001, and 453 passed, 18 failed, 35 skipped for class 002.
- In `run-38610363998/README.md`, 518 is **collected tests** at `f5d48c9`, of which 506
  passed and 12 skipped.

The 12-test difference between the two runs is `tests/test_policy_store.py`, which gained
exactly twelve test functions covering the PostgreSQL policy store (PR 52, merged as
`b31c978`). The 003 experiment in PR 53 added no test functions; it extended an existing
suite-integrity test with assertions about the 003 wiring. Whether the twelve skipped tests in
the run-11 local suite are the same twelve added by PR 52 is not established by this check.
