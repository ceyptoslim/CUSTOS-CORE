# Sabotage Class `fail-closed-proxy` — Pre-Registered Experiment Design

**Status:** FROZEN. This file is hash-pinned in `.github/workflows/ci-red-proof.yml`
and verified before the sabotage runs, so the criteria cannot be adjusted after the
result is known.

**Class id:** `007-weaken-fail-closed-proxy`
**Target control:** the MCP proxy's fail-closed behavior — the property that a gate
that does not answer usably produces a refusal rather than a forward.

## Why this class exists

Classes 001–006 weaken the *gate*. This one weakens the *mediation path*, which is
where the gate's answer is consumed. A proxy that consults the gate correctly and
then forwards anyway when the gate is slow or broken has preserved every gate test
and destroyed the guarantee, because the failure mode is "no answer" rather than
"wrong answer". Fail-closed is a claim about what happens when the answer never
arrives, and no gate-level test can observe it.

## The weakening applied

Two edits, both plausible as a careless refactor, one concept:

1. **Gate errors stop denying.** `except Exception` becomes `except ValueError` in
   `McpProxy.call_tool`. The adapter's own guard already raises `ValueError`, so a
   narrowed clause looks redundant rather than reckless; a `RuntimeError` from a
   gate whose backend is down then propagates to the agent instead of becoming a
   denial.
2. **The wait stops being bounded.** `timeout=self._timeout` becomes `timeout=None`.
   Every test still passes if the gate is fast, which is the trap: a bound that is
   never exercised is indistinguishable from a bound that does not exist.

## Pre-registered expected failures

Exactly these two assertions, named before the first execution:

- `tests/test_mcp_proxy.py::test_gate_exception_denies`
- `tests/test_mcp_proxy.py::test_gate_timeout_denies_without_forwarding`

Any additional failure is observed evidence, not a pre-registered expectation, and
must be reported as such rather than folded into the prediction.

## Pre-registered expected non-failures

These must stay green, because they are what separates "the proxy still works from
the gate" from "the proxy works":

- `test_allow_forwards_once_and_returns_the_record_hash`
- `test_deny_never_touches_the_upstream_server`
- `test_only_a_literal_true_authorizes` (all six parametrizations)
- `test_the_core_imports_nothing_from_custos`
- every assertion in `tests/test_mcp_gate_integration.py`

If any of these fail, the weakening touched more than the failure paths and the run
answer is narrower than this document claims.

## Detection boundary

This class does **not** claim the proxy cannot be bypassed. It claims that two
specific failure paths — an erroring gate and an unbounded wait — are the only ones
these two weakenings change, and that the suite refuses a proxy that stops failing
closed. Complete mediation remains a deployment property (exit class `EX-4`), and
outcome binding remains open (exit class `EX-2`).

## Blindness

Weaker than classes 001–003, and stated rather than implied: the same session wrote
the proxy, its tests, and this weakening. That makes the prediction cheap to satisfy
by construction. Two things partially compensate and neither is a substitute for an
independent author: the class was written against a control whose requirement was
named by an external reviewer ("fail closed when CUSTOS is unreachable"), and the
non-failure list above is falsifiable by the run.

A local dry-run was performed on a scratch copy to confirm the patch applies and to
record the observed failure set. The working tree was left untouched and no test in
`tests/test_mcp_proxy.py` was modified to make this easier.

## Faulty-green rule

If the suite stays green, this run is recorded as **FAULTY-GREEN**: the instrument
failed to detect a known-bad change, and the result is a finding about the tests,
not about the proxy.
