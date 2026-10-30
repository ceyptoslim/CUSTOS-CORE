# Trace binding in the record hash — EABC P7 remediation

**Status:** implemented (binding version 1). Closes the nonconformance named in
`docs/design/EABC-CONFORMANCE.md`: `trace_id` was stored beside the record but sat outside the
`record_hash` preimage, so request-level correlation was not covered by the integrity evidence.

## The requirement

EABC `docs/002 — Evidence Model`, "Intrinsically Bound":

> Any identifier that correlates one piece of evidence to another … MUST be covered by the same
> Integrity Evidence that protects the artifact in which it appears. Correlation MUST NOT depend on
> an external mapping, index, or side channel that is not itself integrity-protected.

Chain correlation already satisfied this: `previous_hash`, `content_hash` and `policy_digest` were
inside the preimage. Request correlation did not: `trace_id` was a column next to the record, so a
consumer could read it but could not prove it belonged to that record.

## R1 — Trace identifier is bound from binding version 1

New records carry `binding_version = 1`. At that version the preimage gains:

```
"binding": "v1"          # marker, bound so a record cannot be re-labelled legacy
"trace_id": "<value>"    # only when set
```

A record emitted at version 1 therefore cannot be relabelled as version 0 to drop `trace_id` from
its hash — the marker is inside the preimage, so the relabelled record fails verification.

## R2 — Legacy records verify byte-identically

Version 0 is the pre-existing preimage and is unchanged. Records written before this change keep
verifying forever, and a mixed chain (legacy records followed by bound ones) verifies as a whole.
No migration rewrites history; retroactive binding is impossible by construction, which is stated
as a limitation rather than papered over.

## R3 — One preimage definition, shared by every verifier

`custos.audit.preimage_fields()` / `compute_record_hash()` are the single definition.
`custos.custody._record_hash()` now delegates to them.

This fixed a drift that had nothing to do with trace binding and everything to do with it: the
external custody re-walk implemented only the original six fields, so it recomputed hashes without
`policy_digest` or `tenant_id` and reported `CONTRADICTION` for any store containing cited records —
the exact case the citation arc introduced. The external consumer was verifying a different record
from the emitter. Two definitions of the same hash is a latent contradiction generator; there is now
one.

## Verification

* `tests/test_audit_trace_binding.py` — eight tests: trace bound at emission; mutation of
  `trace_id` fails verification; deletion of `trace_id` fails; downgrading `binding_version` fails;
  legacy record verifies; mixed chain verifies; SQLite round-trip preserves `policy_digest`,
  `tenant_id`, `trace_id`, `binding_version` and re-verifies after reload; an older database gains
  the columns in place without losing rows.
* Full suite: 695 passed, 14 skipped (measured after the truth guards landed; the count in
  README is canonical and guarded by `tests/test_docs_truth.py`).

## Still missing (stated, not implied)

* A pre-registered sabotage class for trace binding. Every other control in this repo has one, and
  this control should not be exempt. Until a class exists, this is a fix with unit coverage, not a
  red-proof.
* Persistence backends previously dropped `policy_digest` and `tenant_id` on round-trip; both are
  now stored and loaded (SQLite `PRAGMA`-based migration, PostgreSQL `ADD COLUMN IF NOT EXISTS`),
  which is what makes the citation survive a restart rather than only an in-process chain.
