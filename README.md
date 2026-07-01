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
  "audit_record_hash": "a3f9c2..."
}
```

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

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

Tests cover the policy engine, rate limiter, API endpoints, input validation, and audit chain. Exact pass count is confirmed in CI on every push.

---

## What Is Implemented (v1.0)

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
| Replay engine (POST /v1/replay) | ✅ |
| Policy diff (POST /v1/policy/diff) | ✅ |
| Decision snapshots (GET /v1/audit/snapshot) | ✅ |
| Structured JSON logging | ✅ |
| OpenTelemetry-compatible tracing | ✅ |
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
| v1.0 | Enterprise Release Candidate | ✅ Current |

---



**Operator guidance:** For Kubernetes deployments, treat policy rules as ephemeral until v1.1. Use the `/v1/policy` API on startup (via an init container or ConfigMap-driven bootstrap script) to re-register tenant policies after each pod start.

---

## CI Status

Every push runs `ruff` lint + `bandit` security scan + `pytest` + Docker build via GitHub Actions.

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
