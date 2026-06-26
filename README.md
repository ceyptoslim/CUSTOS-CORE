# CUSTOS Core

**A policy-governed execution layer that sits between AI systems and production resources, enforcing deterministic decisions and producing verifiable audit evidence.**

CUSTOS evaluates every request against configurable policy rules before it reaches your AI model or automated system. Each decision is logged to a hash-chained audit ledger, making your governance posture auditable, reproducible, and tamper-evident.

---

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

## What Is Implemented (v0.1)

| Component | Status |
|---|---|
| Policy engine (regex rules, DENY/AUDIT/ALLOW) | ✅ |
| Rate limiter (per-client, per-minute/hour/token) | ✅ |
| Input validation layer | ✅ |
| Hash-chained audit ledger (tamper-evident) | ✅ |
| Prometheus metrics | ✅ |
| Grafana dashboard (auto-provisioned) | ✅ |
| Docker Compose stack | ✅ |
| GitHub Actions CI (lint + test + build) | ✅ |
| `/health` and `/ready` endpoints | ✅ |

---

## Roadmap

| Version | Focus |
|---|---|
| v0.1 | Stable Core ← *current* |
| v0.2 | Authentication + Persistent Audit (SQLite) |
| v0.3 | Observability (OpenTelemetry) |
| v0.4 | Replay Engine |
| v0.5 | Multi-tenant Governance |
| v1.0 | Enterprise Release Candidate |

---

## CI Status

Every push runs `ruff` lint + `pytest` + Docker build via GitHub Actions.

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
