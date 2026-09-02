# Security Policy

## Supported Versions

| Version | Supported | Notes |
|---------|-----------|-------|
| 1.3.x   | ✅ Yes    | Current release — OPA/hybrid policy modes |
| 1.2.x   | ✅ Yes    | Execution firewall + security hardening |
| 1.1.x   | ✅ Yes    | Persistent tenant policies |
| 1.0.x   | ✅ Yes    | PostgreSQL audit backend |
| 0.5.x   | ❌ No     | |
| < 0.5   | ❌ No     | |


## Execution Layer Security (v1.3.x)

### SSRF Protection
The execution adapter validates target URLs before any network call:
- HTTPS-only (HTTP targets rejected)
- Private IP ranges blocked (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x)
- IPv6 loopback (::1) and private (fc00::) blocked
- Privileged ports (<1024) blocked
- Optional hostname allowlist via `CUSTOS_TARGET_ALLOWLIST`

**DNS-rebinding hardening (v1.2+):** Hostnames are resolved to IP addresses
via `getaddrinfo()` before SSRF validation. If the resolved IP falls within a
blocked range, the request is denied. This closes the DNS-rebinding vector
identified in the v1.2 security audit.

**Remaining SSRF consideration:** TOCTOU (time-of-check/time-of-use) between
DNS resolution and the actual HTTP connection is a known theoretical vector.
Production deployments behind a corporate proxy can further mitigate this by
routing through a resolver that pins the resolved IP.

### Circuit Breaker
- **Per-target** (v1.2+): Each downstream host has its own circuit breaker,
  not a global one. A failure on one target does not block others.
- Opens after 5 consecutive downstream failures (configurable)
- Auto-transitions to half-open after 30s (configurable)
- When open, requests are blocked (503) without contacting the target
- Manual reset available via `POST /v1/execute/circuit/reset`

### Fail-Closed Design
The execution firewall never forwards on any error:
- Policy DENY → target never contacted
- Validation failure → blocked
- Rate limit exceeded → blocked
- Downstream timeout → blocked, failure recorded
- Downstream connection error → blocked, failure recorded
- Any unexpected exception → blocked, failure recorded
- Circuit breaker open → blocked (503)

### Policy Engine Modes (v1.3.0+)

CUSTOS-CORE supports three policy engine modes via `CUSTOS_POLICY_ENGINE`:

| Mode | Behavior | Fail Mode | Use Case |
|------|----------|-----------|----------|
| `regex` (default) | Local deterministic pattern matching | N/A (no external dep) | Baseline enforcement, no infrastructure |
| `opa` | OPA/Rego is authoritative | **Fail-closed** (DENY if OPA unavailable) | OPA is the security boundary |
| `hybrid` | Regex first → OPA second | **Graceful fallback** to regex if OPA down | Availability prioritized |

**Pure OPA mode** fails CLOSED: if the OPA server is unavailable, returns
malformed data, or times out, all requests are denied. This is the
restrictive default for production security boundaries.

**Hybrid mode** does NOT fail closed: if OPA is unavailable, the regex
engine's decision is preserved. The regex engine provides baseline PII and
prompt-injection protection without any external dependency.

**OPA/regex semantic parity:** The Rego policy implements the same
governance categories as the regex engine (SSN, credit card, prompt
injection, sensitive keywords), but rule semantics are not perfectly
identical. The regex engine includes Luhn validation for credit cards and
a broader prompt-injection pattern set. OPA provides extensibility for
tenant-specific and business-logic rules. The precise claim is: OPA
implements the current governance policy set and can extend it, but its
rule semantics are not perfectly identical to the regex engine.

### Tenant Authorization

**JWT ↔ client_id binding (v1.2+):** The JWT `sub` claim is compared to
`req.client_id`. If they do not match, the request is rejected with 403.
This prevents a valid JWT holder from impersonating another client.

**Tenant boundary:** Requests specify `tenant_id` which is resolved via
`TenantManager`. Unknown tenant IDs are rejected (v1.3.1+) rather than
falling back to the default tenant. This closes the cross-tenant access
vector identified in the v1.3.0 forensic audit.

**Production authentication override:** `CUSTOS_ENV=production` overrides
`AUTH_DISABLED=1`. In production mode, authentication is always required
regardless of the `AUTH_DISABLED` flag.

### Content Safety
- Raw request content is never logged — only SHA-256 hashes
- Response previews are truncated to 500 characters
- Custom headers passed to downstream but not logged in plaintext

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: heathtavares@retool.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

You will receive a response within 48 hours. If the vulnerability is confirmed, a patch will be issued within 7 days for critical issues.

## Security Design Principles

**1. Content is never stored raw**
The audit chain stores SHA-256 hashes of evaluated content, never the content itself.

**2. Audit chain is tamper-evident (not WORM/immutable)**
Each audit record contains a hash of the previous record. Any modification to historical records breaks chain verification (`GET /v1/audit/verify`). This provides tamper-evidence, not immutability. True WORM storage and blockchain-backed immutability are future architecture targets.

**3. Secrets injected at runtime, never in source control**
Credentials are environment variables. Local development uses `.env` (gitignored). Beta/staging/production should use Secrets Manager / Vault / Kubernetes Secrets. The `.env` file is for local development only.

**4. Non-root container**
The Docker image runs as a non-root `custos` user.

**5. Input validation before policy evaluation**
All requests pass through `InputValidator` before reaching the policy engine, preventing oversized or malformed payloads from reaching core logic.

## Known Limitations

- OPA/regex parity: The two policy engines implement the same governance categories but not identical rule semantics (see Policy Engine Modes above).
- OPA response typing: OPA authorization responses use strict Boolean validation — only literal `True` authorizes (v1.3.1+). Prior versions used `bool()` which could accept truthy non-boolean values.
- Metrics counters are not atomic. Under extreme concurrent load, counts may drift slightly.
- Downstream execution tests use mocked targets. A real downstream integration test against a controlled HTTPS endpoint is planned.
- Solana/Ethereum/ZK trust layers, WORM storage, and compliance certifications (SOC 2, ISO 27001, HIPAA) are architecture targets, not implemented or certified.
