# CUSTOS Core
https://youtu.be/5xzmC5jI8Z8?si=WS09_EzQxETXYlvz

![CI](https://github.com/ceyptoslim/CUSTOS-CORE/actions/workflows/ci.yml/badge.svg)

**A policy-governed execution layer that sits between AI systems and production resources, enforcing deterministic decisions and producing verifiable audit evidence.**

CUSTOS evaluates every request against configurable policy rules before it reaches your AI model or automated system. Each decision is logged to a hash-chained audit ledger, making your governance posture auditable, reproducible, and tamper-evident.

---
### WHY CUSTOS-CORE ?

Zero Third-Party Risk: Runs 100% self-hosted inside your VPC or Kubernetes clusters via Helm—your prompt data never leaves your environment.

Cryptographic Defensibility: Instantly generate tamper-evident snapshots to prove your AI compliance posture to auditors (SOC 2 / HIPAA / ISO 42001).

Precedence-Enforced Safety: Hardcoded regulatory DENY policies take absolute priority over volatile, non-deterministic LLM behavior

## What CUSTOS Does

```
Incoming Request
      │
      ▼
 Input Validation  ──── malformed/oversized? ──→ 422
      │
      ▼
 Rate Limiter      ──── quota exceeded? ──→ 429
      │
      ▼
 Policy Engine     ──── deny rule matched? ──→ blocked
      │
      ▼
 Audit Chain       ──── hash-chained record written
      │
      ▼
 Response          ──── allowed | denied | flagged
```

---

## Quickstart

```bash
git clone https://github.com/ceyptoslim/CUSTOS-CORE.git
cd CUSTOS-CORE
docker compose up --build
```

| Service    | URL                   |
|------------|-----------------------|
| CUSTOS API | http://localhost:8000 |
| Prometheus | http://localhost:9090 |
| Grafana    | http://localhost:3000 |

Grafana login: `admin` / `custos_admin`

---

## Core Endpoints

### `POST /v1/evaluate`
Evaluate a request against active policies and rate limits.

```bash
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{"client_id": "default", "content": "Summarize this document"}'
```

```json
{
  "allowed": true,
  "action": "allow",
  "triggered_rule": null,
  "reason": "No policy violations detected",
  "client_id": "default",
  "tenant_id": "default",
  "audit_record_hash": "a3f9c2..."
}
```

> The Quickstart `docker compose up` stack sets `AUTH_DISABLED=1` so this
> works with zero setup. Production deployments have JWT auth **on by
> default** — see [Authentication](#authentication) below.

### `POST /v1/tenants/{tenant_id}/policy`
Add a custom policy rule for a tenant. Persisted via `PolicyStore` — survives
restarts when `POLICY_DB_PATH` or `DATABASE_URL` is configured. Closes #20.

```bash
curl -X POST http://localhost:8000/v1/tenants/default/policy \
  -H "Content-Type: application/json" \
  -d '{"name": "block_competitor_name", "pattern": "(?i)acme-competitor", "action": "deny", "reason": "Competitor mention policy"}'
```

### `GET /v1/tenants/{tenant_id}/policy`
List custom (non-default) policy rules currently active for a tenant.

### `GET /health`
Service status and uptime.

### `GET /ready`
Kubernetes readiness probe. Returns per-subsystem status.

### `GET /metrics`
Prometheus-compatible metrics exposition.

### `GET /v1/info`
Version, audit backend type, tenant count, and uptime.

### `GET /v1/audit`
Full audit chain. Filter by client: `?client_id=default`

### `GET /v1/audit/verify`
Cryptographic integrity check of the entire audit chain.

---

## Authentication

JWT auth is **on by default** for `/v1/evaluate`. Set `CUSTOS_JWT_SECRET` to a
strong secret in production and issue tokens with `custos.auth.create_token()`:

```python
from custos.auth import create_token
token = create_token(client_id="my-service")
```

```bash
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"client_id": "my-service", "content": "Summarize this document"}'
```

For local development only, set `AUTH_DISABLED=1` to skip token verification
entirely (this is what `docker-compose.yml` does for the Quickstart above).
Never set `AUTH_DISABLED=1` in a production deployment.

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

Tests cover the policy engine, rate limiter, API endpoints, input validation, and audit chain. Exact pass count is confirmed in CI on every push.

---

## What Is Implemented (v1.1)

| Component | Status |
|---|---|
| Policy engine (regex rules, DENY/AUDIT/ALLOW) | ✅ |
| Rate limiter (per-client, per-minute/hour/token) | ✅ |
| Input validation layer | ✅ |
| Hash-chained audit ledger (tamper-evident) | ✅ |
| SQLite audit persistence (survives restarts) | ✅ |
| PostgreSQL audit backend (production-grade) | ✅ |
| JWT authentication on /v1/evaluate | ✅ |
| Multi-tenant governance (isolated per tenant) | ✅ |
| Tenant policy rule API + persistence (`/v1/tenants/{id}/policy`) | ✅ |
| Replay engine (POST /v1/replay) | ✅ |
| Policy diff (POST /v1/policy/diff) | ✅ |
| Decision snapshots (GET /v1/audit/snapshot) | ✅ |
| Structured JSON logging | ✅ |
| OpenTelemetry tracing — console by default, OTLP export optional | ✅ |
| Prometheus metrics | ✅ |
| Grafana dashboard (auto-provisioned) | ✅ |
| Docker Compose stack | ✅ |
| Kubernetes manifests (k8s/) | ✅ |
| Helm chart (charts/custos/) | ✅ |
| GitHub Actions CI (ruff + bandit + pytest + docker) | ✅ |
| `/health`, `/ready`, `/v1/info` endpoints | ✅ |

---

## Roadmap

| Version | Focus | Status |
|---|---|---|
| v0.1 | Stable Core | ✅ Shipped |
| v0.2 | Authentication + Persistent Audit | ✅ Shipped |
| v0.3 | Observability | ✅ Shipped |
| v0.4 | Replay Engine | ✅ Shipped |
| v0.5 | Multi-tenant Governance | ✅ Shipped |
| v1.0 | Enterprise Release Candidate | ✅ Shipped |
| v1.1 | Policy Persistence + OTLP Export | ✅ Current |

---

## Known Limitations (v1.1)

| Area | Status | Notes |
|---|---|---|
| Tenant policy persistence | ✅ Available, opt-in | Custom rules added via `POST /v1/tenants/{id}/policy` survive restarts **only** when `POLICY_DB_PATH` or `DATABASE_URL` is set. With the default in-memory backend, custom rules are still lost on restart — this is expected for local/dev use. |
| OTLP trace export | ✅ Available, opt-in | Set `OTEL_EXPORTER_OTLP_ENDPOINT` and install `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-grpc`. Without the endpoint set (or without the packages installed), tracing gracefully falls back to console JSON output — trace IDs still appear in logs and API responses either way. |
| Policy engine | ⚠️ Regex-based | Sufficient for MVP/PII/prompt-injection patterns. Sophisticated adversaries may craft inputs that bypass rules. Production upgrade path: OPA integration (tracked as a future focus area). |

**Operator guidance:** For Kubernetes deployments where policy customization matters, set `POLICY_DB_PATH` (SQLite, single replica) or `DATABASE_URL` (PostgreSQL, multi-replica) so rules registered via the API survive rollouts, autoscaling, and rescheduling.

---

## CI Status

Every push runs `ruff` lint + `bandit` security scan + `pytest` + Docker build via GitHub Actions.

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
