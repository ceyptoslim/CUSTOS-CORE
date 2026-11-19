# The two figures that share the digits 506

Written 2026-11-17. Kept outside the frozen observation sets on purpose: the files under
`run-38495005061/` and `run-38610363998/` are pinned by digest in their own manifests, so a
note added to either of them would break the very check the manifests exist to support.
Run 11's `MANIFEST.md` records `README.md` as `fc9d18d8…`; editing that README changes its
digest and makes the frozen set fail its own verification. Read this file instead.

## 506 as a total (run 10)

Run 38495005061, head `925f96eabe`, record spec v3. Both sabotage classes report **506
collected**, of which 35 were skipped:

| Class | Result |
|---|---|
| `001-weaken-admin-auth` | 6 failed, 465 passed |
| `002-invert-opa-deny` | 18 failed, 453 passed |

465 + 6 + 35 = 506.

## 506 as a count of passes (run 11)

Run 38610363998, head `f5d48c929e`. The local suite reported **506 passed with 12 skipped**,
so 518 collected. The CI job for the same commit reported 518 collected, 2 failed, 481 passed
and 35 skipped, because CI skips 23 additional tests that a local run does not.

## Why the two differ by twelve

518 − 506 = 12, and the twelve are `tests/test_policy_store.py`, which gained exactly twelve
test functions between the two heads (PR 52, merged `b31c978`, "PostgreSQLPolicyBackend
coverage"). The 003 sabotage class (PR 53, merge `f5d48c9`) added **no** test functions; it
extended an existing suite-integrity test with assertions about the 003 wiring, which changes
no count.

The twelve are mock-based. The module header states "PostgreSQLPolicyBackend (mock-based; no
live DB required in CI)", and the tests patch a stateful fake `psycopg2` into `sys.modules`.
They cover the backend's statements and ordering, not PostgreSQL's behaviour against a server,
so the older real-database coverage gap is not closed by them.

## Reading rule

A figure quoted without its basis is unusable here. "506" alone cannot tell a reader whether
it counts collected tests at `925f96eabe` or passing tests at `f5d48c929e`, and the two runs
are one commit and one PR apart.
