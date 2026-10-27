# Sabotage Class `citation` — Pre-Registered Experiment Design

**Status: FROZEN before first execution.** This file's SHA-256 is pinned in
`.github/workflows/ci-red-proof.yml`; the workflow verifies the hash before
any citation step runs. Neither party revises these criteria after the first
execution exists. The first preserved run is the finding, whichever way it
goes.

This class covers policy-commit citation at emission
(`custos/policy_citation.py`, `custos/action_gate.py`,
`custos/custody.py` P5/P6, design
`docs/design/policy-commit-citation.md`, PR #67): every emitted audit
record cites the sha256 digest of the exact in-force policy set the
decision was enforced against. The requirement was named in external
technical review (October 2026): declared-before versus observed-at-runtime
— a hash-chained, externally anchored log proves the record was not
rewritten, but does not prove the enforced decision cites the committed
object. Citation closes that provenance vector. This class tests whether
the project can PROVE the binding holds: a record emitted under a changed
policy must cite the NEW in-force digest, or the record is citing X while
the gate did Y.

---

## Part A — Suite-sabotage: `005-weaken-citation`

### Target control (already shipped, not artificial)

`custos/action_gate.py` — `ActionGate._cited_policy_digest()` (R2 of the
design): the content-keyed cache whose key is
`(frozenset(tools), engine.rules_digest)`, plus the explicit invalidation
in `register_tools()`. Together these give the binding property: the very
next record after ANY in-force policy change cites the new digest while
steady-state emission stays one cached read (R5).

### Injected modification class

Two lines, the minimal natural weakening of the binding at both mutation
vectors:

1. The content-key check is dropped:

```
if cached is not None and cached[0] == key:
```
becomes
```
if cached is not None:
```

The gate returns the first digest it ever computed for the tenant, on
every evaluation, forever. A rule change mid-stream leaves records
citing the old policy set while enforcement uses the new one.

2. The tools-change invalidation is dropped — the line
`self._digest_cache.pop(tenant_id, None)` in `register_tools()` is
deleted — so a tool-allowlist change no longer forces recomputation.

The sabotage script verifies BOTH patches actually applied and fails the
run otherwise — a silent no-op would produce a false FAULTY-GREEN.

### Expected suite outcome

RED. Pre-registered expected failing assertions, stated in advance:

- `tests/test_policy_citation.py::TestCitationAtEmission::test_record_cites_in_force_policy_digest`
  — the record emitted after a mid-stream `register_tools` change must
  cite the NEW in-force digest; with the invalidation removed it cites
  the stale one.
- `tests/test_policy_citation.py::TestCitationAtEmission::test_rule_change_also_changes_citation`
  — the digest must change after `add_rule`; with the key check dropped
  the stale digest is returned.

These two and only these two are expected to fail; the full failure set is
recorded (no `-x`), per record spec v3. Any additional failure beyond the
two named assertions is recorded as observed, not pre-registered.

### Faulty-green position, stated in advance

If the suite stays green on the weakened citation, that is a
FAULTY-GREEN event: the suite cannot detect the exact regression the
class exists for, and the finding is reported as such.

### Blindness — disclosed, weaker than 003

The author of this design also authored the citation implementation AND
its test suite. No blindness claim is available. Partial external
grounding is disclosed instead: the REQUIREMENT this class guards was
named by an external peer critique (October 2026 technical exchange,
`docs/design/policy-commit-citation.md` provenance), not by the author.
