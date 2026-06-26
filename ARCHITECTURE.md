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

**Current limitation:** The chain is in-memory only. A restart clears it. Persistence to SQLite/PostgreSQL is planned for v0.2.

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

OpenTelemetry tracing is planned for v0.3.

---

## Package Structure

```
CUSTOS-CORE/
├── main.py                          # FastAPI app, routes, singletons
├── custos/
│   ├── __init__.py                  # Package metadata
│   ├── policy_engine.py             # Rule evaluation logic
│   ├── rate_limiter.py              # Per-client quota enforcement
│   ├── audit.py                     # Hash-chained audit ledger
│   ├── models.py                    # Pydantic request/response schemas
│   └── validation.py               # Input validation layer
├── tests/
│   ├── test_policy_engine.py        # Policy engine unit tests
│   ├── test_rate_limiter.py         # Rate limiter unit tests
│   └── test_api.py                  # API integration tests
├── observability/
│   ├── prometheus.yml               # Prometheus scrape config
│   └── grafana/
│       ├── dashboards/custos.json   # Pre-built Grafana dashboard
│       └── provisioning/            # Auto-provisioning config
├── .github/workflows/ci.yml         # GitHub Actions CI
├── Dockerfile                       # Container definition
├── docker-compose.yml               # Full stack (API + Prometheus + Grafana)
└── requirements.txt                 # Python dependencies
```

---

## Planned Roadmap

### v0.2 — Authentication + Persistent Audit
- JWT or API-key authentication on `/v1/evaluate`
- SQLite-backed audit persistence (survives restarts)
- Structured error responses

### v0.3 — Observability
- OpenTelemetry tracing end-to-end
- Structured JSON logging
- Trace correlation between audit records and spans

### v0.4 — Replay Engine
- Reproduce any historical decision from the audit chain
- Policy diff: show how a decision would change under a new policy version
- Decision snapshots for compliance exports

### v0.5 — Multi-tenant Governance
- Per-tenant policy namespaces
- Tenant isolation in rate limiting and audit chain
- Policy version registry with rollback

### v1.0 — Enterprise Release Candidate
- PostgreSQL for audit persistence
- Kubernetes manifests and Helm chart
- Security scanning in CI (Bandit, dependency audit)
- Stable public API with versioning
