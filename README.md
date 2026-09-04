# CUSTOS Platform

## Overview

A multi-layer AI governance platform composed of:

1. **CUSTOS-CORE** — execution-governance and security foundation (open source)
2. **LORL-9.1** — governed agent orchestration layer (open source)
3. **Base44 applications** — application-specific workflows, integrations, operational interfaces, and commercial services built on top of that foundation (proprietary)
4. **External services** — YouTube/Google OAuth and other third-party integrations (application layer)

CUSTOS-CORE and LORL-9.1 provide the open-core governance and agent infrastructure. The Base44 applications provide application-specific workflows, integrations, operational interfaces, and commercial services built on top of that foundation.

---

## Open Source Core

### CUSTOS-CORE

[github.com/ceyptoslim/CUSTOS-CORE](https://github.com/ceyptoslim/CUSTOS-CORE)

**Verified:** 2026-09-04 live run on `main` | **Tests:** 380 passed, 12 skipped | **Coverage:** 88%

Verified implementation:

| Feature | Status | Evidence |
|---------|--------|----------|
| `/v1/evaluate` policy decision API | ✅ Implemented | `main.py:239` — FastAPI endpoint, three-mode policy engine (regex default / OPA / hybrid) |
| `/v1/execute` enforcement firewall | 🔒 Enterprise | Assembled by `custos-enterprise` router — components (`execution.py`, `firewall.py`) are public |
| JWT authentication (HS256) | ✅ Implemented | `custos/auth.py` — `CUSTOS_JWT_SECRET`, `verify_token()`, `auth_enabled()` |
| Tenant authorization binding | ✅ Implemented | `main.py:244,589` — JWT `sub` compared to `req.client_id`, cross-tenant = 403 |
| Rate limiting | ✅ Implemented | `custos/rate_limiter.py` — `QuotaConfig`, `RateLimiter`, per-tenant quotas |
| Hash-chained audit trail | ✅ Implemented | `custos/audit.py` — SHA-256 `content_hash`, `record_hash`, `previous_hash` |
| Input validation | ✅ Implemented | `custos/validation.py` — SSN, credit card, prompt injection, PII patterns |
| SSRF protection (DNS-rebinding) | ✅ Implemented | `custos/execution.py:93` — `getaddrinfo()` resolves hostname to IP before check |
| Per-target circuit breaker | ✅ Implemented | `custos/execution.py:210` — `dict[str, CircuitState]` keyed by target host |
| Production fail-closed auth | ✅ Implemented | `custos/auth.py:96` — `CUSTOS_ENV=production` overrides `AUTH_DISABLED=1` |
| PostgreSQL audit backend | ✅ Implemented | `custos/audit.py:110` — `PostgreSQLBackend` with `psycopg2` |
| OTLP/OpenTelemetry tracing | ✅ Implemented | `custos/tracing.py` — `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc` |
| Docker deployment | ✅ Implemented | `Dockerfile`, `docker-compose.yml` |
| Kubernetes/Helm deployment | 🔒 Enterprise | Moved to `custos-enterprise` (private). Public repo ships Docker/Docker Compose. |
| Prometheus metrics | ✅ Implemented | `main.py:192` — `/metrics` endpoint |

**Policy engine (v1.3.0+):** Three modes selectable via `CUSTOS_POLICY_ENGINE`: `regex` (default — pattern matching + Luhn validation, zero dependencies), `opa` (Rego enforcement via `policies/custos_governance.rego` and an OPA server — fails CLOSED if OPA is unavailable), and `hybrid` (regex first, then OPA, graceful fallback to regex). OPA and hybrid modes are CI-gated against a real OPA 1.0.0 server (`opa-integration` job). LORL-9.1 additionally runs its OWN separate OPA client for agent/treaty governance, which fails OPEN (best-effort).

**Audit trail:** Tamper-evident hash-chained. NOT WORM/immutable storage. Events are append-only with SHA-256 content hashes and chained record hashes, but the storage backend (SQLite/PostgreSQL) is not write-once-read-many.

**Authentication vs. authorization:** JWT handles authentication (who are you). Tenant authorization binding (JWT `sub` = `client_id`) handles authorization (can you access this tenant's resources). These are separate concerns, both implemented.

### LORL-9.1

[github.com/ceyptoslim/LORL-9.1](https://github.com/ceyptoslim/LORL-9.1)

**Verified:** 2026-09-04 live run on `main` | **Tests:** 87 passed | **Coverage:** 93%

Verified implementation:

| Feature | Status | Evidence |
|---------|--------|----------|
| LiteratureAgent | ✅ Implemented | `lorl/agents/literature_agent.py` — deterministic |
| SkepticAgent | ✅ Implemented | `lorl/agents/skeptic_agent.py` — deterministic |
| AuditorAgent | ✅ Implemented | `lorl/agents/auditor_agent.py` — deterministic |
| BaseAgent | ✅ Implemented | `lorl/agents/base_agent.py` — abstract base |
| Ollama/Llama3 integration | ✅ Implemented | `lorl/agents/ollama_client.py` — async HTTP, model="llama3", `/api/generate` |
| EventLedger | ✅ Implemented | `lorl/core/ledger.py` — SHA-256 content hash, append-only, SQLite, `verify_integrity()` |
| Ed25519 identity | ✅ Implemented | `lorl/core/identity.py` — `Ed25519PrivateKey`, `Ed25519PublicKey`, `create()`, `verify()` |
| Treaty engine | ✅ Implemented | `lorl/core/treaty_engine.py` — state machine: PROPOSED → ACCEPTED/REJECTED → EXPIRED/CANCELLED |
| CUSTOS governance client | ✅ Implemented | `lorl/governance/custos_client.py` — calls CUSTOS `/v1/evaluate` with JWT HS256 |
| Governed executor | ✅ Implemented | `lorl/governance/governed_executor.py` — wraps agent + CUSTOS eval + event ledger |
| OPA/Rego policy enforcement | ✅ Implemented | `lorl/governance/opa_client.py` — async HTTP to OPA server, `/v1/data/lorl/governance/allow` |
| Policy enforcer | ✅ Implemented | `lorl/governance/policy_enforcer.py` — `check_treaty_proposal()`, `check_agent_decision()` |

**API endpoints:** `/health`, `/ready`, `/api/v1/labs` (register + list), `/api/v1/treaties` (propose, accept, reject, list), `/api/v1/audit`, `/api/v1/agents/execute`, `/api/v1/agents/governed-execute`

**OPA fail mode:** OPA client fails OPEN — if OPA server is unavailable, returns `(True, [])` with a warning log. This is a permissive best-effort layer.

**CUSTOS fail mode:** CUSTOS client fails CLOSED — if CUSTOS server is unavailable, returns `{"allowed": False}`. The GovernedExecutor flags the result as `ungoverned: True` and logs to the event ledger, but does NOT block the agent's response from being returned.

**Key distinction:** CUSTOS-CORE ships its own OPA/Rego enforcement (v1.3.0+, fail-closed). LORL-9.1 runs a separate OPA client for agent/treaty policy (fail-open, best-effort). Both are true — they are different layers:

- CUSTOS-CORE: policy engine with regex (default), OPA (fail-closed), and hybrid modes
- LORL-9.1: separate OPA-backed agent governance layer on top of CUSTOS

---

## Enterprise Capabilities

Features available in the enterprise tier, verified as implemented in the codebase but gated behind enterprise licensing:

### CUSTOS-CORE Enterprise (Private Repo)
- `/v1/execute` enforcement firewall (blocks/forwards targets) — assembled by `custos-enterprise` router
- DNS-rebinding SSRF protection (`getaddrinfo` resolution)
- Per-target circuit breaker (not global)
- Production fail-closed authentication
- Tenant authorization binding (cross-tenant = 403)
- PostgreSQL audit backend
- OTLP/OpenTelemetry tracing
- Kubernetes/Helm deployment (see `custos-enterprise` — private repo)
- Multi-tenant policy persistence
- Policy diff/replay/snapshot

### LORL-9.1 Enterprise
- Ollama/Llama3 integration (zero-cost local inference)
- CUSTOS governance wiring (CustosClient + GovernedExecutor)
- OPA/Rego policy enforcement
- Governed agent execution API endpoint

---

## Applications

Base44-hosted applications providing operational interfaces, workflows, and commercial services. These are proprietary, not on GitHub.

### CUSTOS-CORE Media Bridge
Media governance and YouTube management dashboard.
- Channel management (5 channels)
- Agent task orchestration (20 running tasks: Trend Spotter, SEO Optimizer, Comment Moderator, Competitor Analyst, Playlist Manager)
- AEGIS Engine audit events
- YouTube connection management with Google OAuth

### QueryForge
CUSTOS business operations hub and data analysis platform.
- CUSTOS policy management (3 active policies)
- Agent registry (10 registered agents)
- Project milestones (13 across two phases)
- Sales CRM (observed prospect deal-value range: $1.2K–$240K)
- CSV/SQL analysis tools

### InsightFlow
Audit logging and YouTube video upload workflow.
- Audit logs (actor, role, action, outcome)
- Video upload lifecycle (queue → upload → complete)
- YouTube/Google OAuth credential management (3 credentials with YouTube API scopes)

### DeployFlow
Deployment platform with template/plugin marketplace.
- App deployment tracking (4 apps across React, Node, Next.js, Vue)
- CI/CD pipeline management (5 deployment records with commit tracking)
- Template/plugin marketplace (8 items, $15–$59)
- Analytics event infrastructure

---

## Integrations

External service integrations live in the application layer (Base44 apps), NOT in the CUSTOS-CORE or LORL-9.1 GitHub repositories.

| Integration | Location | Auth Method |
|-------------|----------|-------------|
| YouTube Data API | InsightFlow, Media Bridge | Google OAuth 2.0 (youtube.upload, youtube.readonly, yt-analytics.readonly) |
| Google OAuth | InsightFlow, Media Bridge | OAuth 2.0 (userinfo.email) |
| CUSTOS-CORE API | LORL-9.1 (CustosClient) | JWT HS256 |
| OPA policy server | CUSTOS-CORE (`opa`/`hybrid` modes, fail-closed) + LORL-9.1 (OPAClient, fail-open) | HTTP (localhost:8181) |
| Ollama inference | LORL-9.1 (OllamaClient) | HTTP (localhost:11434) |

Google OAuth credentials do NOT exist in the CUSTOS-CORE GitHub repository. The credentials belong to the Base44 application layer, which is a separate authentication domain from CUSTOS-CORE's JWT-based API security.

---

## Roadmap / Future

Architecture targets that are NOT yet implemented. These should not be presented as existing features.

- Treaty expansion (multi-party, complex terms)
- Multi-ledger trust anchoring (Solana, Ethereum L2)
- Zero-knowledge privacy proofs
- Advanced dispute/settlement mechanisms
- Exchange API
- Trust Registry (cross-platform, beyond LORL-9.1's Ed25519 identity)
- SOC 2 / ISO 27001 / HIPAA compliance certification (currently "aligned to", not "certified")
- WORM/immutable storage (currently tamper-evident hash-chained)

---

## Honest Claims Reference

| Claim | Correct | Incorrect |
|-------|---------|-----------|
| "Tamper-evident hash-chained audit" | ✅ | |
| "WORM/immutable storage" | | ❌ — use "tamper-evident" |
| "Regex-based policy engine" (CUSTOS-CORE) | ✅ (as default mode) | |
| "OPA-powered" (CUSTOS-CORE) | ✅ (v1.3.0+ — `opa`/`hybrid` modes, CI-gated) | |
| "OPA-backed agent governance" (LORL-9.1) | ✅ | |
| "Compliance-aligned controls" | ✅ | |
| "SOC 2/ISO 27001/HIPAA certified" | | ❌ — use "aligned to" |
| "Google OAuth in Base44 apps" | ✅ | |
| "Google OAuth in CUSTOS-CORE" | | ❌ — not in the codebase |
| "Solana/Ethereum/ZK implemented" | | ❌ — architecture target |
| "380 tests, 88% coverage" (CUSTOS-CORE) | ✅ | |
| "87 tests, 93% coverage" (LORL-9.1) | ✅ | |

For formal audit: authoritative evidence should be commit SHA + CI run + test output + coverage artifact, not a document stating test counts.
