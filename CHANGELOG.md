# CUSTOS Core — Changelog
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

