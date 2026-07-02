# CUSTOS Core — Changelog
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

