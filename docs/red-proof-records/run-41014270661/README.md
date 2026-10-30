# Run 41014270661 — 2026-10-30 (all 7 sabotage classes + 3 custody attacks)

**Verdict: seven classes RED-CONFIRMED, three custody attacks DETECTED, evaluator clean.**
This is the first run that includes class 007, and the first run in which the MCP
proxy's own tests participate in the sabotage proof.

- Workflow run: `41014270661`, `workflow_dispatch` on `main` at `ef37ce3` (merge of PR #87).
- Suite under sabotage: 680 cases, 37 skipped (red-proof environment).
- Every class exited 1; every verdict came from the frozen rule
  `observations.pytest_exit_code != 0 -> RED-CONFIRMED`, never from a listed expectation.

## Class 007, first execution

Pre-registered in `docs/red-proof-records/sabotage-mcp-proxy/DESIGN.md` (hash
`7e517dcf…`, verified in the workflow before the patch is applied). The design named
exactly two failing assertions in advance:

| Pre-registered failure | Observed |
|---|---|
| `test_mcp_proxy::test_gate_timeout_denies_without_forwarding` | failed |
| `test_mcp_proxy::test_gate_exception_denies` | failed |

Two failures observed, two named in advance, no others.

**What the verdict can and cannot say.** The frozen rule is `pytest_exit_code != 0`,
so it reports that the suite went red, not that it went red on the pre-registered
names. The set match above is established by reading the JUnit XML in this record and
comparing it against DESIGN.md, which any re-walker can do in a minute. A third failure
would have left the verdict unchanged and been recorded here as an observation rather
than a pre-registration, which is the honest boundary of an exit-code rule. The weakening propagates two
independent regressions — the wait is unbounded again, and a gate exception raises
through the proxy instead of denying — so the class proves the fail-closed tests hold
that behaviour rather than merely describing it in prose.

The 44 further proxy cases that the DESIGN predicted would *not* fail did not fail,
which is the part that makes the two a signal rather than a general breakage.

## Classes 001–006

| Class | Exit | Failures | Notable |
|---|---|---|---|
| 001 weaken-admin-auth | 1 | 6 | admin endpoints + production auth bypass |
| 002 invert-opa-deny | 1 | 18 | OPA deny inversion, malformed responses, strict typing |
| 003 weaken-action-gate | 1 | 10 | includes 3 `test_mcp_gate_integration` failures — the proxy inherits the gate's weakness |
| 004 weaken-custody-verify | 1 | 1 | internal verify passes, custody contradicts |
| 005 weaken-citation | 1 | 2 | exactly the two pre-registered citation assertions |
| 006 weaken-trace-binding | 1 | 3 | includes the preimage spec-truth guard |

Class 003 is worth reading twice this run: three of its ten failures are end-to-end MCP
proxy tests. A weakened allowlist now shows up through the integration surface as well
as through the gate's own tests, which is the property that makes an integration worth
having. The sabotage itself is unchanged from earlier runs — the disturbance is the
suite growing around a fixed weakening, not the class changing shape.

Section added 2026-10-30 after review: the exit-code rule cannot enforce set equality,
and the skip count moved from 36 to 37 because one new guard (`CUSTOS_TEST_COUNT_STRICT`)
skips outside a live-count environment. No test of the MCP proxy skips: the class's
transport binding does not exist yet, so there is nothing environment-gated to skip.
Artefacts in this directory are byte-identical to the run; only this prose changed, and
MANIFEST.md was regenerated for it.

## Custody attacks

| Attack | Verdict |
|---|---|
| 001 rewrite-backend | DETECTED |
| 002 truncate-tail | DETECTED |
| 003 suppress-anchor | DETECTED |

## What this does not establish

Same boundary as every frozen run, unchanged and worth repeating: these records show
that the suite detects the named weakenings and the named custody attacks **within the
harness**, on this commit, under this evaluator. They do not establish that nothing can
bypass the gate. Complete mediation is a deployment property (EX-4), the executor is
outside this repository's trust boundary (EX-2), and the operator both sets policy and
runs the gate (EX-3, P1). See `docs/design/EABC-EXIT-CLASS-REGISTER.md`.

## Verification

`MANIFEST.md` is a `sha256sum -c` file covering every artifact below.
`sha256sum -c MANIFEST.md` from this directory reproduces each digest; each
`red-proof-junit.xml` lists the failing assertions quoted above.
