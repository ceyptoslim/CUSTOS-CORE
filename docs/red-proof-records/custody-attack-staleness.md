# Custody attack harness staleness — found by run 40936323689

**Date:** 2026-10-29. **Found by:** the first red-proof run after the trace-binding fix (#72) merged.
**Severity:** harness defect, not a product regression. The product got stronger; the attacker did
not notice, and the class reported FAULTY-GREEN for the wrong reason.

## What the run showed

Run [40936323689](https://github.com/ceyptoslim/CUSTOS-CORE/actions/runs/40936323689), class
`006-weaken-trace-binding`: **RED-confirmed**, exit 1, exactly the two pre-registered assertions, 6
other binding tests still passing. All five sabotage classes behaved. Two of three custody attacks
detected.

`001-rewrite-backend` **failed as FAULTY-GREEN**: the observed verdicts did not match the
pre-registration. The observed `internal_verify` was `False` where the design requires `True`.

## Why

`scripts/red-proof/custody_attack.py` carried its own copy of the record-hash preimage
(`_record_hash_fields`) implementing the original six fields. The preimage grew twice — policy
citation (#67) and trace binding (#72) — and the attacker's copy did not.

So when the attack rewrote the store and rehashed the chain, it rehashed with an obsolete algorithm.
The store was then **internally inconsistent** under the real verifier: `AuditLog.verify` returned
`False`. The attack never reached the boundary it was designed to test, because it was caught one
layer early by ordinary chain verification.

This is the same defect class as the one #72 fixed in `custos/custody.py`: a second implementation
of the same hash that silently goes stale. It is worth naming that twice, because it happened twice
in the same file family within a day.

## Why it was not a silent product weakness

The failure direction matters. A stale attacker produces a *false CONTRADICTION* (internal verify
catches a rewrite that a current-algorithm attacker would have hidden), so it fails safe. The
dangerous direction would have been a stale **verifier**, which is exactly what #72 fixed: the
custody re-walk was reporting CONTRADICTION for stores that were fine.

## The fix

`_record_hash_fields` now delegates to `custos.audit.compute_record_hash`. The attacker is always at
least as strong as the verifier, and a future preimage change strengthens the attacker
automatically instead of leaving it behind.

Local re-run of all three attacks after the fix:

| Attack | Internal verify | External verdict | Result |
| --- | --- | --- | --- |
| `001-rewrite-backend` | `True` (attacker hid the rewrite) | `P2 CONTRADICTION` | DETECTED |
| `002-truncate-tail` | `True` | `P4 CONTRADICTION` | DETECTED |
| `003-suppress-anchor` | n/a | gap recorded in-band, cleared on recovery | DETECTED |

Exactly the pre-registered expectations, restored.

## Status and what is owed

* The failed run stays in CI history. It is **not** frozen as an observation set: a FAULTY-GREEN is a
  finding about the harness, and freezing it as evidence would misrepresent it.
* The next `workflow_dispatch` run must be clean across all six classes and three attacks before a
  frozen record is produced for run 40936323689's successor.
* Lesson recorded for the discipline file: an attacker must import the verifier's definition, never
  re-derive it. Anywhere a hash is computed twice, one of the two will eventually be wrong.
