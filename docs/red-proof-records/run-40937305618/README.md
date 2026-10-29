# Run 40937305618 — six classes, three attacks, all as pre-registered

**Run:** https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/40937305618 (run #20, attempt 1)
**Commit:** `2e0cd413` (merge of #75, the docs truth guards)
**Outcome:** 9 of 9 checks passed — six sabotage classes RED, three custody attacks DETECTED.

This is the first run to execute all six pre-registered sabotage classes, and the first clean
run after the harness repair in #76.

## Class 006 `trace-binding` — first clean execution

| Field | Value |
|---|---|
| pytest exit code | 1 |
| JUnit failures | 2 |
| Verdict | RED-CONFIRMED |
| Injection diff sha256 | `141b9303be54d609a1fde9d07d1489caf7cf85eb7d256bf36b4ceecae5f41a94` |
| Sabotage script sha256 | `d59503ee4af322d11dbb5689c1e948d644768f4e5b33bd53a3e81b5d8eae7afe` |

The two failures are exactly the two assertions named before the run existed:

- `test_audit_trace_binding.py::test_mutating_trace_id_breaks_verification`
- `test_audit_trace_binding.py::test_dropping_trace_id_breaks_verification`

The six other tests in that module passed, including the downgrade test
(`test_relabelling_binding_version_breaks_verification`). That asymmetry is the point of the
class: the `binding` marker stayed intact under the injected regression, so a suite that had
only tested the marker would have stayed green. What failed was the identifier.

Matches the prediction recorded in `sabotage-trace-binding/DESIGN.md` before execution,
including the pre-declared non-failures.

## Preceding run 40936323689 — the harness finding

The run immediately before this one (after #72, before #76) produced **FAULTY-GREEN** on
custody attack 001: `internal_verify: False` where `True` was required. Cause was a stale
second copy of the preimage inside `custody_attack.py`, which #76 removed by importing the
canonical definition. Background: `docs/red-proof-records/custody-attack-staleness.md`.

That failed run is deliberately **not** frozen as an observation set. A FAULTY-GREEN is a
finding about the harness; preserving it as evidence would misrepresent it. It remains
inspectable in CI history.

## Custody attacks — restored to pre-registered verdicts

| Attack | Interior | Exterior | Verdict |
|---|---|---|---|
| 001-rewrite-backend | `internal_verify: True` (rewrite hidden) | `P2 CONTRADICTION` | DETECTED |
| 002-truncate-tail | `internal_verify: True` | `P4 CONTRADICTION` | DETECTED |
| 003-suppress-anchor | n/a | gap in-band, cleared on recovery | DETECTED |

## What this does not establish

- The sabotage classes prove the tests detect these specific weakenings, not that the controls
  are unbypassable.
- The attacker is written by the same author as the control and the tests (blindness disclosed
  per class in its DESIGN.md).
- Class 006 exercises in-process completeness over `AuditChain` records; it says nothing about
  Codex or any out-of-band execution path.
- Independent external reconstruction of this run has not been commissioned. Prior runs'
  reconstructions by FactNotebook cover earlier commits, not this one.

## Files

`MANIFEST.md` lists every artifact with its sha256 and byte length. Digests were re-computed
after download, from the bytes in this directory.
