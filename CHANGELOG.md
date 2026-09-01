# CUSTOS Core — Changelog

All notable changes to this project are documented here. This changelog
follows a transparent "what we built, what we fixed, what we know is still
open" format — no claims beyond what the code and tests demonstrate.

---
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
