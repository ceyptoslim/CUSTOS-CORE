# Unpinned files in the frozen observation sets

**Purpose.** Record, with a digest, any file that sits inside a frozen run directory without a
pin in that run's `MANIFEST.md`, so the gap is visible rather than silent and the file's bytes
are checkable in the meantime.

The guard in `tests/test_frozen_manifests.py` enforces two rules: every pinned file must match
its digest, and every file present must be pinned. Files listed here are the explicit exceptions
to the second rule, and removing an entry from the guard's `KNOWN_UNPINNED` set is the test for
whether the gap was closed.

## Recorded gaps

| Run directory | File | SHA-256 recorded here | Recorded | Closed | Why it was outside the pin set |
|---|---|---|---|---|---|
| `run-40937305618` | `README.md` | `ee369a89efd3b7ae6c0c15112477eb1546773195a3b649c4f546d72b9e92fdd7` | 2026-11-19 | 2026-11-19 | The manifest's contents section never mentions the README, so the file was outside the pin set from the start. |

No gap is currently open.

## What the closure changed, and what it preserves

Runs 38610363998 and 38811246068 pin their READMEs, so pinning is this project's convention and
the omission above was an accident rather than a policy. The pin was added on 2026-11-19 as a
single appended row, `| run-40937305618/README.md | ee369a89… | 3234 |`, with no existing line
altered, and the guard's `KNOWN_UNPINNED` entry was removed in the same commit, which is the test
that the gap is gone.

The manifest's own digest moved from `fee4c27a8543655031c4b2e957808b1dc30d11cd54798f631fdaf31263e68ba4` to `74c8aeb9d5d7ed03532a6a39f7b6b295fe3f3f1c83cec18946bf948ddb47f4fa` as a result. That
change is the honest cost of the fix and it is recorded here so nobody has to infer it: a manifest
edited after the fact no longer demonstrates what was frozen, and the only defence is that the
edit is one appended row, dated, with its before and after digest written down beside it.

Nothing in this repository cites `run-40937305618/MANIFEST.md` by digest, which is what made the
amendment safe. If that changes, this file is the record of when the manifest changed and why.
