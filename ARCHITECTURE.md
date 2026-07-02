# CUSTOS Core — Architecture

## What CUSTOS Is

CUSTOS is a policy-governed execution layer that sits between AI systems and production resources. It enforces deterministic policy decisions on every request, rate-limits clients, and produces a cryptographically verifiable audit trail — without requiring external infrastructure beyond a single Docker container.

The core design principle is: **every decision is recorded, every record is verifiable, and no record can be silently modified.**

---

## Why It Exists

Most AI governance tools focus on logging what happened after the fact. CUSTOS focuses on making decisions before execution and making those decisions reproducible and auditable.

The difference:

| Logging Tool | CUSTOS |
|---|---|
| Records what happened | Enforces what is allowed |
| Audit is optional | Audit is mandatory |
| Logs can be modified | Chain is tamper-evident |
| Reactive | Deterministic |

---

## System Components

```
┌─────────────────────────────────────────────────────┐
│                    CUSTOS Core                       │
│                                                     │
│  ┌─────────────┐   ┌─────────────┐                  │
│  │  FastAPI    │   │  Prometheus │                  │
│  │  Runtime    │──▶│  Metrics    │                  │
│  │  (main.py)  │   │  /metrics   │                  │
│  └──────┬──────┘   └─────────────┘                  │
│         │                                           │
│  ┌──────▼──────┐                                    │
│  │  Input      │  custos/validation.py              │
│  │  Validator  │                                    │
│  └──────┬──────┘                                    │
│         │                                           │
│  ┌──────▼──────┐                                    │
│  │  Rate       │  custos/rate_limiter.py            │
│  │  Limiter    │                                    │
│  └──────┬──────┘                                    │
│         │                                           │
│  ┌──────▼──────┐                                    │
│  │  Policy     │  custos/policy_engine.py           │
│  │  Engine     │                                    │
│  └──────┬──────┘                                    │
│         │                                           │
│  ┌──────▼──────┐                                    │
│  │  Audit      │  custos/audit.py                   │
│  │  Chain      │                                    │
│  └─────────────┘                                    │
└─────────────────────────────────────────────────────┘
```

---

## How a Request Flows Through the System

Every request to `POST /v1/evaluate` follows this exact sequence:

### Step 1 — Input Validation (`custos/validation.py`)

The request is checked before any business logic runs:

- `client_id` must be a non-empty string, max 128 characters
- `content` must be non-empty, non-blank, max 32,768 bytes
- `token_count` must be a positive integer, max 100,000

A malformed request returns `422` immediately. Nothing else runs.

### Step 2 — Rate Limiting (`custos/rate_limiter.py`)

The client's quota is checked against three sliding windows:

- Requests per minute
- Requests per hour
- Tokens per minute

If any window is exceeded, the request returns `429`. The rate limiter uses `threading.RLock` to prevent deadlocks under concurrent load. Client quotas are isolated — one client exhausting their quota does not affect others.

### Step 3 — Policy Evaluation (`custos/policy_engine.py`)

The content is evaluated against all active rules in order. Rules produce one of three outcomes:

| Action | Meaning |
|---|---|
| `DENY` | Request blocked. Returned immediately. |
| `AUDIT` | Request allowed but flagged. Scanning continues. |
| `ALLOW` | No rule matched. Request passes. |

**Precedence rule:** `DENY` always beats `AUDIT`, regardless of rule order. If content matches both an AUDIT rule and a DENY rule, the request is denied.

Default rules cover: SSN patterns, credit card patterns, prompt injection attempts, and sensitive keyword flagging.

### Step 4 — Audit Chain (`custos/audit.py`)

Every request — allowed, denied, or rate-limited — is written to the audit chain. The chain cannot be bypassed.

Each record contains:

- Timestamp
- Client ID
- Decision (`allow` / `deny` / `audit` / `rate_limited`)
- Triggered rule (if any)
- Reason
- SHA-256 hash of the evaluated content (never the raw content)
- SHA-256 hash of the previous record
- SHA-256 hash of this record

The chain starts from a fixed genesis hash. Any modification to any historical record breaks all subsequent hashes. Integrity is verifiable at any time via `GET /v1/audit/verify`.

### Step 5 — Response

The response includes the decision, the triggered rule if any, the reason, and the hash of the audit record that was written. The caller can store this hash and later verify it against the audit chain.

---

## How the Audit Chain Works

```
Genesis Hash (64 zeros)
        │
        ▼
┌───────────────────┐
│  Record 1         │
│  content_hash     │
│  previous = 0000  │
│  record_hash ─────┼──▶ SHA256(record_1 + previous)
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  Record 2         │
│  content_hash     │
│  previous = hash1 │
│  record_hash ─────┼──▶ SHA256(record_2 + hash1)
└───────────────────┘
        │
        ▼
      ...
```

To tamper with Record 1, an attacker would need to recompute every subsequent hash in the chain — which is detectable because the final hash would not match.

**Persistence:** In-memory by default (dev/test). Set `AUDIT_DB_PATH` for SQLite or `DATABASE_URL` for PostgreSQL to survive restarts — shipped in v0.2 (SQLite) and v1.0 (PostgreSQL). All backends implement the same `verify()` chain-integrity check.

---

## Where Observability Fits

```
CUSTOS API (/metrics)
      │
      ▼ scrape every 10s
Prometheus
      │
      ▼ query
Grafana Dashboard
```

The `/metrics` endpoint exposes Prometheus-format counters:

- `custos_requests_total`
- `custos_requests_allowed`
- `custos_requests_denied`
- `custos_requests_audited`
- `custos_rate_limit_hits`
- `custos_audit_chain_length`
- `custos_uptime_seconds`

Grafana is pre-provisioned with a dashboard that auto-loads on `docker compose up`. No manual configuration required.

Tracing (`custos/tracing.py`) exports spans to console JSON by default. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to export to a real collector (Jaeger, Tempo, Honeycomb) — shipped in v0.3 (console + correlation) and extended with real OTLP export in v1.1.

---

## Package Structure

```
CUSTOS-CORE/
├── main.py                          # FastAPI app, routes, singletons
├── custos/
│   ├── __init__.py                  # Package metadata (__version__)
│   ├── auth.py                      # JWT verification + dev create_token() helper
│   ├── policy_engine.py             # Rule evaluation logic (DEFAULT_RULES, PolicyEngine)
│   ├── policy_store.py              # Pluggable persistence for tenant custom policy rules
│   ├── policy_diff.py               # Compare decisions under current vs. proposed rules
│   ├── rate_limiter.py              # Per-client quota enforcement (sliding windows)
│   ├── audit.py                     # Hash-chained audit ledger, pluggable backends
│   ├── replay.py                    # Reproduce a historical decision by record hash
│   ├── snapshot.py                  # Compliance-export snapshots of the audit chain
│   ├── tenant.py                    # TenantManager — per-tenant isolation + policy restore
│   ├── tracing.py                   # Console + OTLP span export
│   ├── logging.py                   # Structured JSON logging setup
│   ├── models.py                    # Pydantic request/response schemas
│   └── validation.py                # Input validation layer
├── tests/                           # One test file per custos/ module, plus:
│   ├── test_api.py                  # /v1/evaluate + /v1/audit integration tests
│   ├── test_tenant.py                # Tenant isolation + tenant API tests
│   └── test_policy_persistence.py   # End-to-end proof rules survive a restart
├── observability/
│   ├── prometheus.yml               # Prometheus scrape config
│   └── grafana/
│       ├── dashboards/custos.json   # Pre-built Grafana dashboard
│       └── provisioning/            # Auto-provisioning config
├── k8s/                              # Kubernetes manifests (deployment, service, configmap)
├── charts/custos/                    # Helm chart for one-command cluster deployment
├── .github/workflows/ci.yml         # GitHub Actions CI (ruff + bandit + pytest + docker)
├── Dockerfile                       # Container definition (non-root user)
├── docker-compose.yml               # Full local stack (API + Prometheus + Grafana)
└── requirements.txt                 # Python dependencies
```

---

## Version History

### v0.1 — Stable Core
- Policy engine, rate limiter, input validation, in-memory audit chain
- Prometheus metrics, Docker Compose stack with Prometheus + Grafana

### v0.2 — Authentication + Persistent Audit
- JWT authentication on `/v1/evaluate` (`custos/auth.py`)
- SQLite-backed audit persistence (survives restarts)
- Structured error responses

### v0.3 — Observability
- OpenTelemetry-style tracing end-to-end (console export)
- Structured JSON logging (`custos/logging.py`)
- Trace correlation between audit records and spans

### v0.4 — Replay Engine
- Reproduce any historical decision from the audit chain (`custos/replay.py`)
- Policy diff: show how a decision would change under a new policy version
- Decision snapshots for compliance exports (`custos/snapshot.py`)

### v0.5 — Multi-tenant Governance
- Per-tenant policy, rate-limiter, and audit chain isolation (`custos/tenant.py`)
- `POST/GET/DELETE /v1/tenants` — tenant lifecycle API

### v1.0 — Enterprise Release Candidate
- PostgreSQL backend for audit persistence
- Kubernetes manifests and Helm chart
- Security scanning in CI (Bandit)
- Stable public API with `X-CUSTOS-Version` header and `/v1/info`

### v1.1 — Policy Persistence + OTLP Export
- `custos/policy_store.py` — pluggable storage (in-memory / SQLite / PostgreSQL)
  for tenant-specific custom policy rules, wired into `TenantManager` so both
  the tenant and its rules are restored on startup (`POLICY_DB_PATH` /
  `DATABASE_URL`). `POST/GET /v1/tenants/{tenant_id}/policy` exposes it.
- `OTLPExporter` in `custos/tracing.py` — real trace export to Jaeger, Tempo,
  or Honeycomb via `OTEL_EXPORTER_OTLP_ENDPOINT`, with graceful console
  fallback if the optional `opentelemetry` packages aren't installed.

## Planned (Not Yet Built)
- OPA integration to replace regex-based policy matching
- Policy version registry with rollback
- RS256 / JWKS auth for multi-tenant production use
- Distributed (multi-replica) rate limiting — current limiter is per-pod
