# Run 40512412014 — Frozen Observation Set (Run #18)

First official execution of red-proof class `005-weaken-citation`
(dispatch on `293ec98`, post-merge of PR #67 citation implementation +
PR #68 class pre-registration). The full run executed all five sabotage
classes and all three custody attacks on the same commit:

- 001-weaken-admin-auth — RED
- 002-invert-opa-deny — RED
- 003-weaken-action-gate — RED
- 004-weaken-custody-verify — RED
- 005-weaken-citation — RED (first execution; records in this directory)
- custody attacks 001-rewrite-backend / 002-truncate-tail /
  003-suppress-anchor — all DETECTED

## Class 005 outcome vs the frozen pre-registration

The pre-registration
(`../sabotage-citation/DESIGN.md`, SHA-256 `8709bf77…`, pinned in
`.github/workflows/ci-red-proof.yml` and verified by the workflow before
the citation steps ran) predicted RED with exactly two failing
assertions. The observed outcome matched exactly:

- `pytest_exit_code`: 1 (RED-CONFIRMED, rule v3)
- Total test cases: 576; failed: 2; skipped: 36 (integration tests skip
  in the red-proof job environment — consistent with prior runs, e.g.
  35 skipped in run 38610363998)
- Failing assertions — exactly the two named in advance, and no others:
  - `tests.test_policy_citation.TestCitationAtEmission::test_record_cites_in_force_policy_digest`
  - `tests.test_policy_citation.TestCitationAtEmission::test_rule_change_also_changes_citation`

The injected regression is the two-line weakening of the R2 citation
binding (content-key check dropped from `_cited_policy_digest`;
`register_tools` invalidation deleted), sealed in
`005-weaken-citation/red-proof-injection-diff.patch`
(SHA-256 `03dd4156…`). A record emitted under a changed policy citing the
stale digest — citing X while doing Y — is detected by the suite. The
detection boundary is precisely the two assertions the pre-registration
named.

Blindness position: disclosed in the DESIGN (author wrote design,
implementation, and tests; partial external grounding — the requirement
was named by an external peer critique, October 2026). Patch mechanics
were dry-run verified against a scratch copy before the class was
registered; the first suite execution under the known-bad patch is this
run.

Identity: run_id 40512412014, run_number 18, run_attempt 1, commit
`293ec98cde2c9a51a079eb0bcbe8896f9c269e7b`,
sabotage_script_sha256 `d1330f059174ff4ee4282cc7974deca04547229930d47fa53dece10c0c064513`.
