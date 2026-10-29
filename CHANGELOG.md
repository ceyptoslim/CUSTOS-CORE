# CUSTOS Core — Changelog

All notable changes to this project are documented here. This changelog
follows a transparent "what we built, what we fixed, what we know is still
open" format — no claims beyond what the code and tests demonstrate.

---
---

## [Unreleased]

### Added — exit-class register mapped to EABC v1 (profile-level, per review)
- Mapping of each exit class onto existing EABC properties: `EX-1` -> P6/P2, `EX-2` -> P3/P4/P8,
  `EX-3` -> P1/P5 + docs/002 external-mapping rule, `EX-4` -> P2. None is one-to-one except `EX-4`,
  which is close enough to be flagged in the document as the weakest justification in the register.
  If the contract's author judges `EX-4` redundant, it should be dropped; the claim survives on the
  three classes that each cut across at least two properties.
- Non-exhaustiveness stated where the vocabulary is defined: "closed for comparability, not for
  truth". CI enforces shape and never completeness, and the checker's failure message now says so.
- Written revision procedure for a fifth class: name the failure mode, show distinctness from the
  nearest existing class, name the property it dents and why that property cannot express it, state
  the artifact and falsification condition, and change list, mapping and test in one commit.
- Checkers added: every class must appear in the mapping table with a property citation and no empty
  cell; the mapping section may not introduce aggregation vocabulary and must carry its own
  "adds no levels" disclaimer. Verified by mutation: dropping a class from the mapping fails, and a
  "weighted total" sentence fails.
- Counts: 603 passed / 14 skipped, coverage 89% (measured).

### Added — EABC exit-class register (profile-level statement against EABC v1)
- `docs/design/EABC-EXIT-CLASS-REGISTER.md`: four exit classes (`suppression`, `substitution`,
  `attribution`, `coverage`), each with boundary, failure mode, declared status, threat-model
  assumptions, artifact and falsification condition. Statuses drawn from a closed vocabulary:
  `demonstrated-closed`, `declared-open`, `out-of-scope-by-construction`.
- The register exists because EABC v1 grades evidence depth per property and cannot express that
  P1's hole and P2's hole are different kinds of hole. This profile previously read "partial" four
  times for four unrelated failures.
- `out-of-scope-by-construction` requires an architectural argument and a falsification condition for
  the declaration itself, demonstrated on pre-binding-v1 records: closing that class retroactively
  would break byte-identical verification of historical chains, so it is closed by a constraint
  rather than by a missing test.
- `tests/test_exit_class_register.py` enforces the shape: six fields per class, closed status
  vocabulary, closed class list, every cited artifact path must exist, non-trivial falsification
  conditions, and the architectural argument for out-of-scope. Verified by three mutations before
  committing (invented status, stripped argument, broken artifact path) — each one fails with its
  own message.
- Counts: 603 passed / 14 skipped, coverage 89% (measured).

### Changed — the published preimage formula is now a test
- `tests/test_preimage_spec_truth.py`: intercepts the dict `compute_record_hash` actually passes
  to `json.dumps` and asserts it matches the field list published in
  `docs/design/EABC-PROFILE.md`. Interception, not reconstruction: the guard reads the real
  preimage instead of re-deriving it, so it cannot become the fourth stale copy.
- Also guards the two consumers that were stale copies in production —
  `custos/custody.py` and `scripts/red-proof/custody_attack.py` — and structurally (AST) rejects
  any module outside `custos/audit.py` that assembles a preimage dict of its own. `custody.py`
  reading `previous_hash` during a re-walk is not flagged; building the dict is.
- Verified in both directions before committing: deleting `trace_id` from the published formula
  fails with "an independent implementer would compute a different hash", and a synthetic
  duplicate module is detected while `hybrid_engine`'s decision dict and the custody re-walk are
  correctly ignored.
- Counts: 579 passed / 14 skipped, coverage 89% (measured).

### Security — red-proof run 20: six classes, first clean class 006
- Run 40937305618: all six pre-registered sabotage classes RED, all three custody attacks DETECTED.
- Class `trace-binding` (006) RED-CONFIRMED on first clean execution; the two failures are the
  two assertions named before the run, and the six other binding tests passed, including the
  downgrade test that isolates the identifier from the marker.
- Observation set frozen at `docs/red-proof-records/run-40937305618/` with per-file digests.
- The preceding run's FAULTY-GREEN (stale attacker preimage) is documented, not frozen.

### Changed — documentation truth guards (numbers that cannot drift)
- `tests/test_docs_truth.py`: static guards that fail the suite when the documented test
  count and the actual state diverge. Enforces one canonical count (README verified line),
  agreement from `NOTICE.md` and the README claims table, a dated + commit-addressed
  verification line, and no competing *current* counts anywhere else in the docs.
  Historical statements (CHANGELOG releases, dated essays, frozen red-proof records) are
  exempt by design: retro-editing them would falsify the record.
- Why this exists: README advertised 550 passed while the suite was at 571, and its own
  claims table stated 90% coverage against a header claiming 88%. Both numbers were
  plausible; two were wrong. The class of error is now a failing test instead of a habit.
- The live cross-check (canonical count versus this environment's collected tests) is opt-in
  via `CUSTOS_TEST_COUNT_STRICT=1`, because collection differs between local runs and the
  red-proof workflow. A guard that fails for environmental reasons gets ignored, which is
  worse than no guard.
- Counts synced: README, NOTICE and the claims table now state **575 passed / 14 skipped**
  (measured), coverage 89% (measured this run).

### Security — Red-proof class `trace-binding` (pre-registered, 6th class)
- `docs/red-proof-records/sabotage-trace-binding/DESIGN.md`: FROZEN pre-registration,
  hash-pinned in `ci-red-proof.yml` and verified with `sha256sum -c` before the class runs.
  Injected regression: `trace_id` deleted from the record-hash preimage while the `binding`
  marker is left intact — the tidy-up a well-meaning refactor performs on a field that looks
  redundant. Pre-registered failing assertions, named in advance and **exactly**:
  `test_mutating_trace_id_breaks_verification` and `test_dropping_trace_id_breaks_verification`.
  Predicted non-failures stated before the run (the downgrade test must still pass, which
  isolates the identifier from the version marker).
- `scripts/ci-sabotage/006-weaken-trace-binding.sh`: known-bad patch with dual integrity
  guards, including one asserting the marker survived (the wrong weakening is a plausible
  error and would test the wrong property).
- Local dry-run against a scratch tree: **exactly the two pre-registered failures, 6 passed**,
  matching the stated predictions. The class has NOT yet executed in CI; the permanent
  observation record is produced by the workflow run, not by this pre-registration.

### Documentation — EABC conformance declared (partial, self-assessed)
- `docs/design/EABC-CONFORMANCE.md`: self-assessment against the open
  Execution Authority Boundary Contract (EABC, `omwei-org/omwei-eabc`
  docs/001–004). Claims **Level 1 partial / Level 2 partial**, no Level 3
  claim. Satisfied rows cite the artifact that proves them (P5 state
  binding via the citation-at-emission arc and pre-registered class 005;
  P6 conditionally on custody anchoring). Unsatisfied properties are named
  with the work each requires rather than omitted: P1 (attester separation
  — the operator sets policy and runs the gate), P3 (execution outcome not
  recorded), P4 (no per-action authority credential), P2 (complete
  mediation is a deployment property).
- `docs/design/EABC-PROFILE.md`: implementation profile mapping components
  and record fields onto the eight normative properties, with unsupported
  capabilities stated explicitly.
- Not a certification or third-party audit. The EABC specification is
  published by another party; this document is a voluntary self-assessment
  that a reader is expected to check against the code and frozen records.

### Fixed — trace binding in the record hash (EABC P7)
- `custos/audit.py`: `AuditRecord.binding_version` (default 0 = legacy
  preimage, byte-identical, unchanged forever). Records emitted from
  version 1 include a bound `"binding": "v1"` marker plus `trace_id` in the
  `record_hash` preimage, so request-level correlation is covered by the
  same integrity evidence as the record it correlates — and a record cannot
  be relabelled legacy to drop its trace identifier.
- `custos/audit.py`: `preimage_fields()` / `compute_record_hash()` are now
  the single preimage definition.
- `docs/design/eabc-trace-binding.md`: R1–R3, including the disclosed
  limitation (pre-version-1 records cannot be retroactively bound).

### Fixed — two defects found while mapping against EABC
- `custos/custody.py`: the external custody re-walk (`verify_custody` P1)
  recomputed the record hash from the original six fields only, ignoring
  `policy_digest` and `tenant_id`. Any store containing cited records was
  therefore reported as `CONTRADICTION` — the independent verifier was
  checking a different record from the one the emitter wrote. It now
  delegates to `compute_record_hash()`, so the external consumer recomputes
  exactly what was emitted.
- `custos/audit.py` (SQLite and PostgreSQL backends): `policy_digest`,
  `tenant_id` and `binding_version` were not persisted, so a restart
  silently stripped the citation and the reloaded chain failed
  verification. Both backends now store and load them, with in-place
  migration (`PRAGMA table_info` + `ALTER TABLE` for SQLite,
  `ADD COLUMN IF NOT EXISTS` for PostgreSQL).
- `tests/test_audit_trace_binding.py`: 8 tests — binding at emission,
  mutation of `trace_id` fails, deletion fails, version downgrade fails,
  legacy record verifies unchanged, mixed legacy/bound chain verifies,
  SQLite round-trip preserves citation and binding, older database migrates
  in place.
- Test suite: **571 passed / 13 skipped** (was 550/13).

### Documentation — benchmark receipt committed
- `docs/benchmarks/bench-oct24.json`: the benchmark record backing the
  publicly cited "1.47ms p50" (hs256 sequential, 1.475ms p50 / 1.679ms p95,
  300 requests, zero errors) and "1,122 rps" (16-worker concurrent
  throughput) figures, generated 2026-10-25T01:00Z, single uvicorn replica,
  4-vCPU Linux sandbox. Includes rs256 mode. Committed so every public
  performance claim is checkable against the artifact, per the same
  receipts discipline as the red-proof records.
- `docs/benchmarks/README.md`: record provenance, environment, and the
  exact harness invocation for reproduction (`scripts/benchmark_evaluate.py`,
  already in-repo). Numbers vary with hardware; the committed record is the
  receipt for its stated environment, not a hardware-independent guarantee.

### Security — Red-proof class `custody` (pre-registered, infrastructure)
- `docs/red-proof-records/sabotage-custody/DESIGN.md`: FROZEN pre-registration
  for the custody class, SHA-256 pinned in the workflow. Part A:
  `004-weaken-custody-verify` suite-sabotage — weaken the P2
  anchored-head reconciliation; suite must go RED (extends the
  faulty-green matrix to the custody module; disclosed weaker-blindness
  position documented). Part B: attack class — the anchors must catch
  what the internal chain cannot.
- `scripts/ci-sabotage/004-weaken-custody-verify.sh`: known-bad patch with
  integrity guard, mirroring classes 001-003.
- `scripts/red-proof/custody_attack.py`: executes the three pre-registered
  attacks at CI scale on a real deployment shape (SQLite chain +
  GitAnchorSink on a real git repo): 001-rewrite-backend (internal verify
  GREEN on a consistently rewritten store, external P2 CONTRADICTION),
  002-truncate-tail (P4 CONTRADICTION), 003-suppress-anchor (gap recorded
  in-band, enforcement unaffected — fail-visible). Job FAILS if any
  expected verdict does not occur (faulty-green for custody).
- Workflow: `004-weaken-custody-verify` joins the sabotage matrix;
  new `custody-attacks` job (DESIGN.md hash verified before execution;
  evidence records uploaded with if:always()).
- First official execution complete (run 40426037722, workflow_dispatch
  on 0fc516e): all seven classes confirmed — 004-weaken-custody-verify
  RED-CONFIRMED with exactly the one pre-registered failing assertion
  (TestRewriteAndRehash, P2 anchored-head reconciliation); custody attacks
  001-rewrite-backend / 002-truncate-tail / 003-suppress-anchor all
  DETECTED with actual == expected (internal verify GREEN on the
  consistently rewritten store, external anchors CONTRADICTION at P2/P4;
  gap recorded in-band, enforcement unaffected). Observation set frozen
  permanently at `docs/red-proof-records/run-40426037722/` (27 files,
  SHA-256 manifest). The weekly schedule re-proves all four sabotage
  classes and all three attacks on every run.

### Security — Chain-head custody (docs/design/chain-head-custody.md, PR #60 design)
- `custos/custody.py`: external custody of audit chain heads — per-tenant
  hash-chained anchors (epoch, chain_length, head_hash) emitted every
  `CUSTOS_CUSTODY_ANCHOR_N` records / `CUSTOS_CUSTODY_ANCHOR_T` seconds.
- Sinks: `GitAnchorSink` (append-only external git repo — append rights,
  not history-rewrite rights) and `TSAAnchorSink` (RFC 3161 timestamps,
  token stored as opaque bytes, verified externally via
  `openssl ts -verify`). Pluggable `CustodySink` protocol.
- `verify_custody()`: the external re-walk — recomputes the record chain
  from a backend copy and reconciles it against the external anchor log,
  emitting ESTABLISHED / CANNOT ESTABLISH / CONTRADICTION per proposition.
  A consistent rewrite-and-rehash of the store passes internal
  verification and CONTRADICTS the anchors (P2) — the boundary the
  internal chain cannot draw on its own.
- Fail-visible, not fail-blocking: sink outages never block enforcement;
  gaps are recorded in the next successful anchor and surfaced via
  `/ready` (ok / disabled / pending / stale / fail — reporting only,
  never gates readiness) and `/metrics`
  (`custos_custody_enabled`, `custos_custody_sink_health`,
  `custos_custody_anchor_age_seconds`).
- Additive and disabled by default (`CUSTOS_CUSTODY_ENABLED`); no hot-path
  changes beyond a lock-scoped `AuditChain.head()` read.
- Companion red-proof class `custody` pre-registered in the design
  (custody-001 rewrite-backend, custody-002 truncate-tail,
  custody-003 suppress-anchor); execution to follow the established
  DESIGN.md-frozen discipline.

### Security — RS256/JWKS authentication (PR #57)
- Dual-algorithm JWT verification: HS256 backward compatible, RS256
  production path (`CUSTOS_JWT_ALGORITHM=RS256` + `CUSTOS_JWT_PRIVATE_KEY`,
  explicit key required at startup in production — fail-closed).
- JWKS discovery at `/.well-known/jwks.json` (RFC 7517, RFC 7638-style
  `kid`); tenant-issued tokens verify against tenant JWKS URLs
  (`CUSTOS_TENANT_JWKS_URL[_<ISSUER_SLUG>]`, https-only, TLS mandatory,
  no redirects, kid lookup with TTL cache and refresh-on-unknown-kid).
- Algorithm confusion structurally closed: verification branches on the
  token header; RS256-header tokens never touch symmetric secrets,
  `alg=none` rejected; dev-default shared secrets never authorize in
  production, even in RS256 deployments.
- Re-proved against the red-proof protocol on merge day: run
  39322985909 (run #15) on `c4a3d93` — all three sabotage classes
  RED-CONFIRMED (001: 6 failures, 002: 18, 003: 2).

### Fixed — tenant quota inheritance (PR #58)
- `/v1/evaluate` auto-registered new per-client rate keys with a hardcoded
  60/min quota, silently ignoring the tenant API's `requests_per_minute`
  contract. New rate keys now inherit the tenant's configured quota via
  `RateLimiter.get_quota()`; the conservative 60/min default remains only
  for tenants without explicit configuration (default-tenant behavior
  unchanged). Surfaced by the new benchmark suite; regression tests in
  `TestTenantQuotaInheritance`.

### Performance — /v1/evaluate benchmark (PR #58)
- Reproducible benchmark (`scripts/benchmark_evaluate.py`,
  `docs/performance/benchmark-v1.md`): governance overhead ~1.5 ms p50 /
  < 2.2 ms p99 end-to-end; > 1,000 req/s per replica; RS256 adds ~0.13 ms
  p50 over HS256. Both ALLOW and DENY governance paths measured.

### Security

- OPA policy engine now enforces custom (tenant) rules locally, with deny-union
  semantics: a custom rule may only add restrictions, never loosen an OPA
  decision. `add_rule()` is no longer a warn-and-ignore no-op; persisted tenant
  rules are enforced on every evaluate path.
- `evaluate_with_metadata()` now applies the same deny-terminal ordering as
  `evaluate()` — an OPA deny can no longer be co-fired into an AUDIT/allow.

### API
- All administrative endpoints moved onto `admin_router`, which carries the
  auth dependency at the router level: new admin endpoints inherit protection
  automatically. A guard test fails loudly if an admin path ever lands on bare
  `@app` without auth.

### CI — red-proof 003 (pre-registered blind experiment, FN-CUSTOS-REDPROOF-002 protocol)

Third sabotage class `003-weaken-action-gate` targets the boundary between
declared authority and actual execution: the minimal natural weakening of
the action gate's deny-by-default tool-allowlist authority check
(un-registered tools proceed past the authorization-decision boundary).
Pre-registered before first execution in
`docs/red-proof-records/sabotage-003/DESIGN.md` (frozen; SHA-256 pinned and
verified by the workflow at run time; no criteria revision after the first
run; the first preserved execution is the finding either way). Two-phase
control probe (`scripts/red-proof/action_gate_probe.py`) records the gate's
decision for a consequential un-registered tool request on the clean build
and after injection — an observed clean/injected delta rather than an
expectation match; the injected probe artifact carries the run_id and
injection_diff_sha256. The probe establishes a violation at the
authorization-decision boundary only; probe and suite results are separate
observations from the same CI run, not independent sources. Blinding
preserved: no local execution of the sabotage before the workflow, and the
injection was written from the implementation's structure, not from the
gate's tests.
- Run 11 observation set (run_id 38610363998, first 003 execution) frozen
  in-repo at docs/red-proof-records/run-38610363998/ with SHA-256
  manifest — all three classes' records plus both control-probe
  artifacts, permanent against CI artifact expiry.
- Run 12 observation set (run_id 38811246068, first execution with the
  observed-equivalence probe instrumentation) frozen in-repo at
  docs/red-proof-records/run-38811246068/ with SHA-256 manifest — the
  probe artifacts record the probe script SHA-256, the commit SHA, and
  a `git status --porcelain` capture in both phases, making clean vs
  injected probe-environment equivalence observable rather than
  inferred (the causal-establishability gap identified in FN-CUSTOS-003).

- Observed-equivalence instrumentation (FN-CUSTOS-003 exchange): the
  control probe now records its own SHA-256, the working-tree commit
  SHA, and a git status --porcelain capture inside BOTH phase
  artifacts. Clean/injected probe-environment equivalence is now an
  observed comparison (same script hash, same commit, pristine tree vs
  the enumerated injection delta) rather than an inference. The frozen
  003 criteria, the verdict rule, and the pinned DESIGN.md are
  unchanged; run 38610363998 remains the first preserved execution as
  recorded.

### CI — red-proof package

**Structured red-proof evidence records** — every red-proof CI run now produces machine-readable records: `red-proof-evidence.json` (sabotage id, sabotage-script SHA-256, commit SHA, pytest exit code, expected vs. actual outcome, verdict RED-CONFIRMED/FAULTY-GREEN, UTC timestamp), `red-proof-junit.xml` (structured execution report), and the pytest output — all uploaded as CI artifacts even on faulty-green, so the enforcement decision is always reproducible against the exact code state and known-bad patch. Meta-test added guarding the records pipeline against silent removal. **v2 (external review feedback):** record restructured into identity (run ID/number/attempt, commit SHA, regression ID, sabotage hash), time (started/completed/generated UTC), raw observations (exit code, JUnit XML + SHA-256, pytest output + SHA-256, CI job outcome) kept separate from the verdict, and a versioned verdict rule (observations -> RED-CONFIRMED/FAULTY-GREEN) with full provenance — the verdict is an assertion about the run, and the observations are what let an independent system check it.
  **v3 (independent external reconstruction FN-CUSTOS-REDPROOF-001, Oct 2026):**
  pytest runs without `-x` so the JUnit records the full failure set of each
  regression class, not just the first failure; the post-injection diff is
  sealed at run time (SHA-256 bound into record identity, uploaded as an
  artifact — contemporaneously bound, not merely replayable); the shell
  writes the exit code to its own artifact file before the record is
  generated, so the integer is observable through a channel independent of
  the record asserting it. Observations gain a `junit_failures` count;
  record_version 3; meta-test hardened to enforce the v3 field set, the
  absence of `-x`, the diff-sealing step, and upload of all five artifacts.
  The run-9 observation set used for the external reconstruction is frozen
  permanently in-repo at `docs/red-proof-records/run-38446904362/`
  (byte-identical artifact copies, SHA-256 manifest), outliving GitHub's
  90-day artifact expiry.
- Suite-integrity meta-tests: every test must assert something real (no
  print-only tests), no vacuous assertions, no unconditional skips, count floor.
- Strictness: `--strict-markers`, `--strict-config`, `xfail_strict`, `-ra` —
  tests can no longer silently degrade to skipped while CI reads green.
- Weekly sabotage workflow: applies known-bad patches and FAILS if the suite
  stays green on them (faulty-green detection). Verified live: sabotage turns
  the suite red (6 and 18 failures), restored suite green.

### Tests
- **550 passed / 13 skipped / 88% coverage** (+56 since v1.3.3: +20 RS256/JWKS
  suite, +2 tenant-quota inheritance regression, +8 OPA custom-rule
  enforcement, +1 admin-router guard, +4 suite-integrity, +1 red-proof
  records pipeline meta-test, PostgreSQL policy-backend coverage, and
  +22 chain-head custody suite (+1 skipped)).

## [1.3.3] — Security Hardening (external audit reconciliation)

### Security
- **SSRF validation is now fail-closed**: unresolvable hostnames block instead of silently
  skipping the DNS check; invalid/unparseable ports raise a clean block instead of crashing.
- **DNS-rebinding TOCTOU closed**: target hostname is resolved once, validated, and the
  outbound request is pinned to exactly the validated IPs (Host header + SNI preserved).
- **Explicit `:443` targets are allowed** (previously rejected as a privileged port).
- **OPA policy engine: `deny` is terminal.** The audit flag can no longer convert a
  deny decision into an allow (deny + audit co-fire resolves to deny).
- **Administrative endpoints require authentication** when auth is enabled: audit log,
  audit verify, snapshots, replay, policy diff, and all tenant management routes.
- **Expired tokens return 401** (RFC 6750) instead of 403.

### Deployment
- `docker-compose.yml`: production now sets `CUSTOS_ENV` (the variable the app actually
  reads — the previous `ENV=production` engaged nothing); Grafana admin password supplied
  via `GRAFANA_ADMIN_PASSWORD` (fail-closed, no shipped default); Prometheus
  `--web.enable-lifecycle` removed.

### Dependencies
- `httpx` 0.27.0 -> 0.28.1 (aligned with LORL-9.1); `PyJWT` 2.13.0 -> 2.15.0
  (fixes 12 published security advisories; `pip-audit` clean).

### Tests
- 480 passed / 12 skipped / 88% coverage (+10 regression tests covering every fix).


## [1.3.2] — Production Secret Fail-Closed Hardening

### Security (P2 audit remediation, PR #36)
- **Fail-closed production JWT secret validation:** `CUSTOS_ENV=production` now
  refuses to start when `CUSTOS_JWT_SECRET` is unset or still the dev default.
  Previously the fallback `dev-secret-change-in-production` remained silently
  active in production; only `AUTH_DISABLED` was guarded. Fail-closed per the
  strict env-presence rule.
- Live boot-verified: production + missing/dev-default secret → startup
  RuntimeError; production + real secret → serves normally.

### Tests
- +6 regression tests (`tests/test_production_secrets.py`): validator both
  directions, startup wiring both ways, dev-mode unchanged.
- Suite now **470 passed, 12 skipped** (was 464/12). Coverage holds at 88%.
- Cleaned 3 pyflakes findings in test files (unused locals, redundant re-import).

## [1.3.1] — Release Integrity & Tenant Authorization Patch

### Forensic Audit Remediation

This patch addresses findings from a forensic audit of the v1.3.0 release.

### Version Synchronization
- `VERSION` in main.py: 1.2.0 → 1.3.1
- `__version__` in custos/__init__.py: 1.2.0 → 1.3.1
- Kubernetes deployment manifests: 1.2.0 → 1.3.1
- Helm Chart version/appVersion: 1.2.0 → 1.3.1
- Helm values tag: 1.2.0 → 1.3.1

### Tenant Authorization (P0/P1)
- **`get_strict()` added to TenantManager** — returns None for unknown
  tenant IDs instead of silently falling back to the default tenant.
- All 6 request-handling endpoints (/v1/evaluate, /v1/execute,
  /v1/audit/records, /v1/audit/verify, /v1/audit/snapshot, /v1/replay)
  now use `get_strict()` and reject unknown tenant IDs with HTTP 403.
- `get_or_default()` is retained only for internal policy management
  operations where creating a new tenant context is expected.
- Cross-tenant audit record isolation verified.

### OPA Response Typing (P1)
- OPA authorization responses now use strict `is True` validation
  instead of `bool()`. Only literal Boolean `True` authorizes.
- String `"true"`, integer `1`, and other truthy non-boolean values
  are rejected as malformed responses (fail-closed).

### SECURITY.md Updated
- DNS-rebinding: documented as fixed (v1.2+ uses getaddrinfo).
- OPA: documented as implemented (v1.3.0+) with three modes.
- Tenant authorization: documented with JWT↔client_id binding and
  strict tenant boundary.
- Audit chain: explicitly labeled "tamper-evident, not WORM/immutable".
- Secrets: "injected at runtime, never in source control" (not just
  ".env file").
- OPA/regex parity: documented that rule semantics are not identical.
- Known limitations: OPA response typing, downstream test status,
  architecture targets clearly labeled as future.

## [1.2.0] — Execution Enforcement Layer

### The Critical Gap This Closes

Prior to v1.2.0, CUSTOS-CORE was a **policy decision API**, not an
**execution firewall**. The `/v1/evaluate` endpoint returned `allowed: false`
as JSON metadata, but nothing in the codebase physically prevented a caller
from ignoring that decision and contacting the downstream target anyway.

This was identified as the #1 gap between the architecture documents
(which describe an "Execution Firewall") and the implementation.

v1.2.0 closes this gap. The new `/v1/execute` endpoint physically blocks
denied requests from reaching downstream targets. A DENY means the target
is never contacted — verified by `test_deny_never_contacts_target` which
asserts `mock.assert_not_called()` on the HTTP client.

### Added

- **custos/execution.py** (283 lines) — HTTP Execution Adapter
  - SSRF protection: blocks private IPs (10.x, 172.16-31.x, 192.168.x,
    127.x, 169.254.x), IPv6 loopback (::1), IPv6 private (fc00::), non-HTTPS
    targets, privileged ports (<1024), and enforces optional hostname
    allowlist via `CUSTOS_TARGET_ALLOWLIST` env var
  - Circuit breaker: opens after N consecutive downstream failures
    (default 5, configurable via `CUSTOS_CIRCUIT_THRESHOLD`), auto-
    transitions to half-open after reset timeout (default 30s, configurable
    via `CUSTOS_CIRCUIT_RESET`), thread-safe state via `threading.Lock`
  - Fail-closed design: every exception type returns `forwarded=False`,
    never raises — timeout, connection error, and unexpected exceptions
    all result in a blocked request
  - Response preview truncated to 500 characters for safety
  - Configurable timeout via `CUSTOS_EXECUTION_TIMEOUT` (default 10s)

- **custos/firewall.py** (240 lines) — Execution Firewall Orchestrator
  - Full enforcement pipeline: validate → rate limit → policy evaluate →
    execute or block → audit
  - DENY = target is never contacted (the fundamental difference from
    `/v1/evaluate`)
  - ALLOW = content is forwarded to the downstream HTTPS target
  - Audit chain records the actual execution outcome: `deny`,
    `forwarded`, `forward_failed`, `circuit_open`, `rate_limited`
  - Tracing spans include forwarded status, status code, and timing
  - Fail-closed: any exception during the pipeline = block, never forward

- **POST /v1/execute** — The enforcement boundary endpoint
  - Returns 403 on DENY (target never contacted)
  - Returns 200 on forwarded ALLOW (with downstream status code + preview)
  - Returns 429 on rate limit exceeded
  - Returns 503 on circuit breaker open
  - Returns 502 on forward failure (downstream timeout, connection refused)
  - Enforces HTTPS on `target_url` via Pydantic validator
  - `X-CUSTOS-Version` header on all responses

- **GET /v1/execute/circuit** — Circuit breaker status endpoint
  - Returns state (closed/open/half_open), failure count, threshold,
    last failure time, reset timeout

- **POST /v1/execute/circuit/reset** — Manual circuit breaker reset
  - Admin operation to force-close the circuit breaker

- **custos/models.py** — New schemas:
  - `ExecuteRequest`: client_id, content, tenant_id, token_count,
    target_url (HTTPS enforced), target_method (GET/POST/PUT/PATCH/DELETE),
    target_headers, target_timeout (1-60s)
  - `ExecuteResponse`: allowed, action, triggered_rule, reason, client_id,
    tenant_id, forwarded, status_code, response_preview, circuit_open,
    audit_record_hash, trace_id
  - `CircuitBreakerStatus`: state, failure_count, failure_threshold,
    last_failure_time, reset_timeout

- **tests/test_execution.py** — 40 new tests:
  - 10 SSRF protection tests (loopback, private IPs, IPv6, allowlist,
    privileged ports, missing hostname, non-HTTPS)
  - 4 circuit breaker tests (open after threshold, half-open after timeout,
    reset on success, initial closed state)
  - 8 HTTP adapter tests (success, SSRF block, timeout, connection error,
    circuit open, unknown error, response truncation, non-HTTPS)
  - 4 DENY enforcement tests (never contacts target, returns 403, prompt
    injection blocked, audit recorded)
  - 4 ALLOW forwarding tests (forwards to target, response preview,
    audit says forwarded, custom headers passed)
  - 1 rate limit test (blocks before forward)
  - 3 fail-closed tests (target down, target timeout, audit records failure)
  - 6 end-to-end API tests (403 on deny, 200 on allow, circuit status,
    circuit reset, SSRF blocked via API, X-CUSTOS-Version header)

- **New metrics**: `custos_executions_forwarded`, `custos_executions_blocked`,
  `custos_circuit_open`

- **New environment variables**:
  - `CUSTOS_TARGET_ALLOWLIST` — comma-separated hostnames (empty = allow any)
  - `CUSTOS_EXECUTION_TIMEOUT` — downstream call timeout (default 10s)
  - `CUSTOS_CIRCUIT_THRESHOLD` — failures before circuit opens (default 5)
  - `CUSTOS_CIRCUIT_RESET` — seconds before half-open (default 30)

### Known Limitations (documented transparently)

- The HTTP execution adapter uses `httpx.Client` (sync). Under high
  concurrency, an async client (`httpx.AsyncClient`) would be more
  appropriate. This is a known optimization, not a bug.
- The SSRF check validates IP literals at parse time but does not resolve
  hostnames to IPs before checking. A determined attacker could
  potentially use DNS rebinding. A production deployment should add DNS
  resolution + IP validation. This is documented as a hardening item.
- The circuit breaker is a single global instance, not per-target.
  Per-target circuit breakers would be more granular but add complexity.
  This is an architecture decision, not a bug.
- No end-to-end test with a real downstream service exists yet. All
  forwarding tests use mocked HTTP clients. A live integration test
  against a test HTTP server is a hardening item.
- The `allowlist` parameter accepts `None` (allow any HTTPS host) by
  default. Production deployments should set `CUSTOS_TARGET_ALLOWLIST`
  to restrict forwarding to approved downstream targets only.

### Stats

- 296 tests passing (up from 260 in v1.1.1)
- 90% coverage (up from 89%)
- New module coverage: execution.py 98%, firewall.py 90%
- Zero regressions in existing tests
- Ruff lint: clean
- Bandit: clean (B104 is expected Docker 0.0.0.0 bind)

### Version Sync

- `main.py` VERSION → 1.2.0
- `custos/__init__.py` __version__ → 1.2.0
- `charts/custos/Chart.yaml` version → 1.2.0, appVersion → 1.2.0
- `charts/custos/values.yaml` image tag → 1.2.0
- `k8s/deployment.yaml` image tag → 1.2.0

---

## [1.1.1] — Policy Persistence Integration Fix

### Fixed
- **Policy rules are now actually persisted.** v1.1.0 shipped `custos/policy_store.py`
  with full unit test coverage and closed issue #20, but `TenantManager` never
  called it — custom tenant policy rules were still lost on every restart in
  practice. This release wires `PolicyStore` into `TenantManager`: rules are
  loaded on tenant registration and the tenant list itself is restored from
  the store on startup.
- Added `POST /v1/tenants/{tenant_id}/policy` and `GET /v1/tenants/{tenant_id}/policy`
  — until this release there was no API surface to actually register a
  tenant-specific policy rule in the first place.
- `tests/test_policy_store.py` only exercised `PolicyStore` in isolation; added
  `tests/test_policy_persistence.py` with end-to-end tests that simulate a
  restart (new `TenantManager` instance, same durable backend) and prove a
  custom rule and its tenant are both restored.
- Fixed `tests/conftest.py` to disable auth via a FastAPI dependency override
  instead of relying on an external `AUTH_DISABLED` env var — `pytest tests/ -v`
  now passes out of the box, matching the README's documented instructions.
- Fixed `docker-compose.yml` Quickstart stack returning 401 on the README's own
  `/v1/evaluate` example (JWT auth is on by default; the dev stack now sets
  `AUTH_DISABLED=1` explicitly, with a comment warning against doing this in
  production).
- Synced version strings that had drifted after the v1.1.0 release: `main.py`
  (`VERSION`), `charts/custos/Chart.yaml` (had a malformed `1.10`),
  `charts/custos/values.yaml` image tag, and `k8s/deployment.yaml` image tag
  and labels all now read `1.1.0`/`1.1.1` consistently.
- Rewrote `.env.example` to document the environment variables the app
  actually reads (`CUSTOS_JWT_SECRET`, `POLICY_DB_PATH`, `AUDIT_DB_PATH`,
  `DATABASE_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `CUSTOS_TRACING`, etc.) —
  it previously only listed placeholder vars that didn't match the code.
- 185 tests passing (up from 176 in v1.1.0; +9 new tests in
  tests/test_policy_persistence.py covering restart-survival and the new
  policy rule endpoints). The 2 existing version-header tests were fixed
  in place to assert against `VERSION` instead of a hardcoded string.

### Docs
- README: Roadmap and "What Is Implemented" now say v1.1, added an
  Authentication section, added a Known Limitations section that accurately
  distinguishes "available but opt-in" from "not yet built."
- ARCHITECTURE.md, SECURITY.md, CONTRIBUTING.md refreshed to match current
  package structure and supported versions (see those files for detail).

---

## [1.1.0] — Policy Persistence + OTLP Export

### Added
- custos/policy_store.py — pluggable policy rule storage
- InMemoryPolicyBackend, SQLitePolicyBackend, PostgreSQLPolicyBackend
- Policy rules survive pod restarts via POLICY_DB_PATH or DATABASE_URL
- OTLPExporter in custos/tracing.py — export to Jaeger, Tempo, Honeycomb
- Set OTEL_EXPORTER_OTLP_ENDPOINT to activate OTLP export
- Graceful fallback to console if packages not installed
- 26 new tests (176 total)

### Closes
- Issue #20 — policy persistence across restarts
- Issue #21 — OTLP trace export

---

## [1.0.0] — Enterprise Release Candidate

### Added
- PostgreSQL audit persistence backend (DATABASE_URL env var)
- SQLite remains default for dev; PostgreSQL for production
- Backend-agnostic AuditChain — same verify() across all backends
- Kubernetes manifests (k8s/deployment.yaml, service.yaml, configmap.yaml)
- Helm chart (charts/custos/) for one-command cluster deployment
- X-CUSTOS-Version response header on all API responses
- /v1/info endpoint — version and backend info
- CHANGELOG.md (this file)

### Changed
- AuditChain constructor now accepts database_url parameter
- main.py version bumped to 1.0.0
- custos/__init__.py version bumped to 1.0.0

### Architecture
- Storage layer is now pluggable: InMemoryBackend, SQLiteBackend, PostgreSQLBackend
- All backends implement the same save() / load_all() / close() interface
- Switching backends requires only an env var change — no code changes

---

## [0.5.0] — Multi-tenant Governance

### Added
- TenantManager — per-tenant isolated policy, rate limiter, audit chain
- POST /v1/tenants — register tenant
- GET /v1/tenants — list tenants
- DELETE /v1/tenants/{id} — remove tenant
- tenant_id field on /v1/evaluate and /v1/replay

---

## [0.4.0] — Replay Engine

### Added
- Replay engine — POST /v1/replay
- Policy diff — POST /v1/policy/diff
- Decision snapshots — GET /v1/audit/snapshot
- Snapshot verification — POST /v1/audit/snapshot/verify

---

## [0.3.0] — Observability

### Added
- Structured JSON logging (custos/logging.py)
- OpenTelemetry-compatible tracing (custos/tracing.py)
- trace_id in EvaluateResponse and audit records

---

## [0.2.0] — Authentication + Persistent Audit

### Added
- JWT authentication on /v1/evaluate
- SQLite audit persistence
- Bandit security scanning in CI
- Test isolation via conftest.py

---

## [0.1.0] — Stable Core

### Added
- FastAPI runtime
- Policy engine (DENY/AUDIT/ALLOW)
- Rate limiter (per-client, sliding windows)
- Hash-chained tamper-evident audit ledger
- Input validation
- Prometheus metrics + Grafana dashboard
- Docker Compose stack
- GitHub Actions CI
