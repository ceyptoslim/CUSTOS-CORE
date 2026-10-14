# Sabotage 003 — Pre-Registered Experiment Design

**Status: FROZEN before first execution.** This file's SHA-256 is pinned in
`.github/workflows/ci-red-proof.yml`; the workflow verifies the hash before
any 003 step runs. Per the protocol agreed with P. Etoua (Oct 14 2026,
FN-CUSTOS-REDPROOF-002 follow-up), neither party revises these criteria after
the first execution exists. The first preserved run is the finding, whichever
way it goes.

## Target control (already shipped, not artificial)

`custos/action_gate.py` — `ActionGate`, the deny-by-default pre-flight action
gate (`/v1/evaluate_action`, documented in `docs/PRE-FLIGHT-ACTION-GATE.md`).
Declared authority = the tenant's registered tool allowlist
(`ActionGate.register_tools`). Actual execution = a proposed action evaluated
before the consequential operation runs. An un-registered tool must be denied.

## Injected modification class

Weaken the declared-authority check in `evaluate_action`:

```
if action.tool not in self._tool_allowlists.get(tenant_id, set()):
```
becomes
```
if False:
```

The deny-by-default branch no longer fires for un-registered tools, which
then fall through to the dangerous-command and content checks. This is the
minimal natural weakening of the authority boundary (mirrors 001's no-op
pattern). The sabotage script verifies the patch actually applied and fails
the run otherwise — a silent no-op would produce a false FAULTY-GREEN.

**Not engineered to dodge tests:** this design was written from the
implementation's structure alone. The author has not read
`tests/test_action_gate.py` since this design was agreed, and no local
execution of the sabotage occurs before the first workflow run.

## Expected violation criterion

Post-injection, a request for a tool NOT on the requesting tenant's
registered allowlist proceeds past the authorization-decision boundary
(gate returns an allow-class decision for that request), where the frozen
pre-injection behavior is DENY (rule `action_gate_tool_not_allowlisted`).

## Control probe (both phases, in-run)

`scripts/red-proof/action_gate_probe.py` constructs a real `TenantManager` +
`ActionGate`, registers tenant `probe_tenant_003` with the single-tool
allowlist `{weather_lookup}`, and requests `payment_transfer` (a
consequential tool, deliberately not registered) with benign arguments.
The probe runs twice in the same CI job:

- **clean phase** — BEFORE the sabotage is applied; records the clean
  decision.
- **injected phase** — AFTER sabotage + diff seal; the artifact carries the
  `run_id` and `injection_diff_sha256`, bound the way the v3 record binds
  the diff, so the decision is tied to this injection and not a generic run.

The probe records decisions; it asserts nothing. The violation is then an
**observed delta** between two recorded decisions (clean vs injected), not
an injected decision measured against an expectation. This closes the
prior-misconfiguration gap: if the clean probe were also to allow, the
record shows it.

## Scope of what the probe establishes (agreed boundary)

An ALLOW on the injected probe establishes a control violation **at the
authorization-decision boundary** — given the request, the tenant allowlist,
the policy and the recorded response. It does NOT establish that the tool
then executed or that any external effect occurred. For 003 the gate
decision is the target. The probe artifact and the test results are separate
observation artifacts but NOT independent sources — both originate in the
same CI run.

## Three distinctions (per the FN-002 protocol)

1. **Modification** — the v3 sealed diff, `injection_diff_sha256` bound into
   the record identity.
2. **Control violation** — the observed delta between the clean and injected
   probe decisions, both hashed into the record.
3. **Detection** — the full suite runs without -x. RED-CONFIRMED means this
   regression was detected, within the boundary the failures define — not
   universal coverage. A green suite is recorded as FAULTY-GREEN: a verdict
   whose substantive meaning must be reconstructed, not assumed.

## Blindness

The injection's first execution is the red-proof workflow itself. No local
pre-run. The outcome is genuinely open: the gate has 32 dedicated test
cases, so detection is plausible — but the injection was not shaped to
provoke or avoid them. Neither party knows the verdict in advance.

## Record additions for 003 (additive; record_version stays 3)

`observations.control_probe_clean` and `observations.control_probe_injected`
— each `{file, sha256}`. No change to the verdict rule, which continues to
map `pytest_exit_code != 0 -> RED-CONFIRMED; else FAULTY-GREEN`.
