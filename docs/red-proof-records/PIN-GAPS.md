# Unpinned files in the frozen observation sets

**Purpose.** Record, with a digest, any file that sits inside a frozen run directory without a
pin in that run's `MANIFEST.md`. The pin gap stays visible and the file's bytes stay checkable
without editing a frozen document.

The guard in `tests/test_frozen_manifests.py` enforces two rules: every pinned file must match
its digest, and every file present must be pinned. Files listed here are the explicit exceptions
to the second rule, and removing an entry from the guard's `KNOWN_UNPINNED` set is the test for
whether the gap was closed.

## Recorded gaps

| Run directory | File | SHA-256 recorded here | Recorded | Why it is not in the manifest |
|---|---|---|---|---|
| `run-40937305618` | `README.md` | `ee369a89efd3b7ae6c0c15112477eb1546773195a3b649c4f546d72b9e92fdd7` | 2026-11-19 | The manifest's contents section never mentions the README, so the file was outside the pin set from the start. |

The recorded digest is of the file as it stands in the tree at the commit that added this note.
A reader can recompute it with `sha256sum docs/red-proof-records/run-40937305618/README.md` and
compare.

## Why the manifest was not amended

Runs 38610363998 and 38811246068 do pin their READMEs, so pinning is this project's convention
and the gap is an omission rather than a policy. Amending `run-40937305618/MANIFEST.md` would
close it, but a manifest edited after the fact no longer shows what was frozen; the record would
gain a pin and lose the evidence that the pin was missing. The digest is recorded here instead,
which makes the file checkable today and leaves the decision to amend the manifest where it
belongs, with the owner of the record.
