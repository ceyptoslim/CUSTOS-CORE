# Run 40426037722 — Custody Red-Proof: First Official Execution

**Run:** GitHub Actions run 40426037722 (workflow_dispatch, 2026-10-27)
**Commit:** 0fc516e (main, merge of PR #62)
**Pre-registered design:** `docs/red-proof-records/sabotage-custody/DESIGN.md`
(SHA-256 pinned in the workflow; verified by the workflow before any
custody step ran.)

## Verdicts — all seven classes confirmed

| Class | Verdict | Record |
|---|---|---|
| 001-weaken-admin-auth | RED-CONFIRMED | 6 failures (unchanged set) |
| 002-invert-opa-deny | RED-CONFIRMED | 18 failures (unchanged set) |
| 003-weaken-action-gate | RED-CONFIRMED | 2 failures (unchanged set; probe pair archived) |
| **004-weaken-custody-verify** | **RED-CONFIRMED** | **exit 1; exactly 1 failure** |
| **custody-attack-001 rewrite-backend** | **DETECTED** | internal verify GREEN, external P2 CONTRADICTION |
| **custody-attack-002 truncate-tail** | **DETECTED** | internal verify GREEN, external P4 CONTRADICTION |
| **custody-attack-003 suppress-anchor** | **DETECTED** | gap recorded in-band; enforcement unaffected |

## The boundary this run demonstrates

Attack 001 executed the full rewrite-and-rehash: a mid-chain record was
modified directly in the SQLite store and every subsequent hash
recomputed, so the chain's own `verify()` passed green on reload. The
external custody verify reported CONTRADICTION at P2 — the anchored heads
no longer match the store. The system's internal check passing is the
pre-registered expected observation; the external anchors catching what
it cannot is the finding.

Sabotage 004 removed exactly that P2 check from the code and the suite
caught the removal at exactly one assertion — the one written to detect
it — confirming the detection boundary is neither accidental nor
incidental.

## Honesty notes

- Attack observations bind `run_id`, `commit_sha`, and
  `attack_script_sha256`; the workflow run binds the same commit.
- Unlike sabotage-003, no blindness claim is available for 004 (same
  author wrote module and tests); this is disclosed in DESIGN.md, and
  the reliability rests on the sealed diff and full re-walkability.
- The attack classes were mechanically validated locally before this
  run (sandbox temp environments; nothing committed); this workflow run
  is the first official record.

## Files

- `001/`–`004/`: v3 evidence records — evidence JSON, JUnit, pytest
  output, sealed injection diff, independent exit-code artifact.
- `003-probe/`: clean/injected probe pair for the action-gate class.
- `custody-attacks/`: observation JSON per attack.
- `MANIFEST.md`: SHA-256 of every file in this set.
