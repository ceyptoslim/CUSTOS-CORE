# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.2.x   | ✅ Yes    |
| 1.1.x   | ✅ Yes    |
| 1.0.x   | ✅ Yes    |
| 0.5.x   | ❌ No     |
| < 0.5   | ❌ No     |


## Execution Layer Security (v1.2.0)

### SSRF Protection
The execution adapter validates target URLs before any network call:
- HTTPS-only (HTTP targets rejected)
- Private IP ranges blocked (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x)
- IPv6 loopback (::1) and private (fc00::) blocked
- Privileged ports (<1024) blocked
- Optional hostname allowlist via `CUSTOS_TARGET_ALLOWLIST`

**Known limitation:** Hostname-to-IP resolution is not performed before
the SSRF check. DNS rebinding could bypass the IP-based checks. Production
deployments should add DNS resolution + IP validation. This is documented
as a hardening item, not a current guarantee.

### Circuit Breaker
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

**2. Audit chain is tamper-evident**
Each audit record contains a hash of the previous record. Any modification to historical records breaks chain verification (`GET /v1/audit/verify`).

**3. No secrets in code**
All credentials are environment variables. See `.env.example`. Never commit `.env`.

**4. Non-root container**
The Docker image runs as a non-root `custos` user.

**5. Input validation before policy evaluation**
All requests pass through `InputValidator` before reaching the policy engine, preventing oversized or malformed payloads from reaching core logic.

## Known Limitations

- Policy engine uses regex matching. Sophisticated adversaries may craft inputs that bypass rules. Production upgrade: replace with OPA.
- Metrics counters are not atomic. Under extreme concurrent load, counts may drift slightly.
  
