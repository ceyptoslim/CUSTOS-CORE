# Sabotage Class `custody` — Pre-Registered Experiment Design

**Status: FROZEN before first execution.** This file's SHA-256 is pinned in
`.github/workflows/ci-red-proof.yml`; the workflow verifies the hash before
any custody step runs. Neither party revises these criteria after the first
execution exists. The first preserved run is the finding, whichever way it
goes.

This class covers the chain-head custody feature
(`custos/custody.py`, design `docs/design/chain-head-custody.md`, PR #61):
external custody of audit chain heads — the boundary conceded in the
red-proof record and raised in external forensic review (Oct 23, 2026):
the audit chain is self-attestation while its writer belongs to the system
under investigation; a consistent rewrite of the store passes internal
verification. Custody externalizes the record of what the chain head was.
This class tests whether the project can PROVE that boundary holds — from
both sides.

---

## Part A — Suite-sabotage: `004-weaken-custody-verify`

### Target control (already shipped, not artificial)

`custos/custody.py` — `verify_custody()`, proposition P2
(`P2_anchored_heads_match_store`): the recomputed record hash at the
anchored length must equal the externally anchored head. P2 is the exact
boundary the design exists to draw: the one check that catches a
consistent rewrite-and-rehash of the audit store after the internal
chain has been fooled.

### Injected modification class

Weaken the P2 reconciliation:

```
if head != a.head_hash:
```
becomes
```
if False:
```

The comparison never fires; a rewritten store reconciles as ESTABLISHED
against the anchors. This is the minimal natural weakening of the custody
boundary (mirrors 001's and 003's no-op pattern). The sabotage script
verifies the patch actually applied and fails the run otherwise — a silent
no-op would produce a false FAULTY-GREEN.

### Expected suite outcome

RED. Pre-registered expected failure focus:
`tests/test_custody.py::TestRewriteAndRehash::test_internal_verify_passes_but_custody_contradicts`
at the P2 assertion. The full failure set is recorded (no `-x`), per
record spec v3.

### Blindness — disclosed, weaker than 003

Unlike sabotage-003, the author of this design also authored the custody
module AND its test suite. There is no blindness claim available here.
Reliability of this class rests instead on: (1) the sealed, contemporaneous
injection diff hashed into the record identity; (2) full re-walkability —
the patch, the diff, the JUnit, and the output are all preserved artifacts;
(3) the matrix runs the identical patch against the identical suite on
three Python versions. This weaker position is stated rather than papered
over.

---

## Part B — Attack class: the anchors must catch what the chain cannot

Executed by `scripts/red-proof/custody_attack.py` in the
`custody-attacks` workflow job. Each attack builds a real deployment
shape — SQLite-backed `AuditChain`, `GitAnchorSink` on a real git
repository — applies a pre-registered attack, and enforces the expected
verdict. A job FAILS if any expected verdict does not occur: that would
mean the custody mechanism failed to detect the exact attack class it
was built to catch (faulty-green for custody).

Attack-script mechanics were validated locally against the public module
before the first workflow execution; the first preserved workflow run is
the first official record. The attacks themselves are already publicly
demonstrated at unit scale in `tests/test_custody.py`; this class
formalizes them at CI scale with evidence records.

### custody-attack-001 — rewrite-backend

The attacker mutates the SQLite store in place: one mid-chain record's
`reason` rewritten, then every subsequent `record_hash` and
`previous_hash` recomputed consistently — the store is internally
coherent again. The chain is then reloaded from the tampered store.

Pre-registered expected verdicts:

| Check | Expected |
|---|---|
| Internal `AuditChain.verify()` on reloaded store | **GREEN** (the boundary: internal verification cannot catch this) |
| External P2 `anchored_heads_match_store` | **CONTRADICTION** (rewrite detected) |
| Overall custody verify | **CONTRADICTION** |

### custody-attack-002 — truncate-tail

The attacker deletes the newest 4 records directly in SQLite. The
truncated store is internally coherent.

Pre-registered expected verdicts:

| Check | Expected |
|---|---|
| Internal `AuditChain.verify()` on reloaded store | **GREEN** |
| External P4 `store_completeness` | **CONTRADICTION** (length discontinuity vs anchored length) |
| Overall custody verify | **CONTRADICTION** |

### custody-attack-003 — suppress-anchor

The attacker destroys the sink repository mid-operation. Fail-visible,
not fail-blocking — the pre-registered expectation is that custody
**surfaces** the outage and enforcement **continues**:

| Check | Expected |
|---|---|
| Enforcement continues while sink is down (no exception) | **YES** |
| Gap recorded and surfaced via `AnchorManager.health()` while down | **YES** |
| Next successful anchor carries the gap in-band (`gap` object) | **YES** |
| Gap state cleared after recovery | **YES** |

### Verdict rule (v1)

`actual == expected -> DETECTED; else FAULTY-GREEN` — the job exits
non-zero on FAULTY-GREEN for every attack, mirroring the suite-sabotage
enforcement.

---

## Boundaries inherited from the design (unchanged by this class)

Custody establishes what the chain head was, at bounded intervals, in
external custody. It does not establish accuracy-at-write; it does not
cover actions that never passed through the gate; the anchor window is
bounded (at most N−1 records may be lost to a store deletion, and the
loss is detectable as a length discontinuity). A green custody run
establishes that the mechanism detected the attack — not that the store
was accurate.
