# Red-Proof Run 38811246068 — Frozen Observation Set (Run #12)

**Status:** FROZEN — permanent observation set, preserved against CI artifact expiry.
**Trigger:** workflow_dispatch (post-merge verification of PR #55, first execution with the
observed-equivalence probe instrumentation).
**Commit:** b06098c

## Run summary

All three sabotage classes recorded RED-CONFIRMED. This run is the first executed with the
observed-equivalence probe instrumentation: both probe phases record the probe script's
own SHA-256, the working-tree commit SHA, and a `git status --porcelain` capture.

## Observed equivalence (003-probe artifacts)

Both probe artifacts carry the same probe script SHA-256 and commit SHA. The clean probe's
porcelain capture records its own output file as the only untracked entry; the injected
probe's capture enumerates exactly one tracked modification (`custos/action_gate.py`)
plus the run's own record artifacts as untracked entries. The tracked-tree delta between
the two probe executions is exactly one file: the gate.

## Scope boundaries (consistent with FN-CUSTOS-003)

The recorded ALLOW concerns the authorization-decision boundary; it does not establish
downstream tool execution or an external effect. The porcelain capture observes the
working tree of the CI job at probe time; the clean probe's executed code state is
hash-bound only insofar as the probe script and tracked tree are bound to the recorded
commit and the enumerated porcelain state.
