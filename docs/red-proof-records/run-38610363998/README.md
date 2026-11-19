# Red-Proof Run 38610363998 (run #11) — Frozen Observation Set

First execution of the pre-registered sabotage 003 experiment
(docs/red-proof-records/sabotage-003/DESIGN.md, SHA-256 pinned in the
workflow and verified at run time). Triggered by workflow_dispatch on
merged main (PR #53, commit f5d48c9) on 2026-10-14. All three sabotage
classes returned RED-CONFIRMED. The 003 verdict: exit code 1, 2 of 518
test cases failed (the fail-closed unit assertion and the API endpoint
assertion), with the clean/injected control-probe delta recorded as
separate hashed observation artifacts.

## Contents

- `001-weaken-admin-auth/`, `002-invert-opa-deny/`,
  `003-weaken-action-gate/` — evidence record, JUnit XML, pytest output,
  independent exit-code artifact, and sealed injection diff per class.
- `003-probe/` — the two-phase control probe artifacts
  (`red-proof-probe-clean.json` pre-sabotage, `red-proof-probe-injected.json`
  post-sabotage; the injected artifact carries the run_id and
  injection_diff_sha256 bound to the record identity).
- `MANIFEST.md` — SHA-256 manifest of every frozen file.

## Reconstruction notes (probe-environment equivalence)

Bearing on the question of whether the clean and injected probes ran in
environments equivalent apart from the injected change:

- Both probe artifacts record the same `run_id` (38610363998): they
  executed as sequential steps of the same CI job, on the same runner
  workspace, from the same checkout of commit f5d48c9.
- The sealed injection diff enumerates the complete set of tracked-file
  changes between the clean and injected executions: one file,
  `custos/action_gate.py`, one line. The probe script, tenant code, and
  policy engine paths are identical at that commit.
- The probe constructs its own tenant state in-process (fresh
  TenantManager, registered allowlist, single request), so the applicable
  tenant policy and state are fully specified by the probe script itself.

What this set does NOT establish: a hash-level binding of the clean
probe's executed code state (the clean artifact predates the diff seal
and carries no code-state hash), or the absence of untracked-file and
environmental deltas within the job. The determining-cause claim
therefore remains a bounded inference from an enumerated diff plus
same-job sequential execution, not an observation.
