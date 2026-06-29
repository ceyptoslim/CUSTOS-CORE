# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ Yes    |
| 0.5.x   | ✅ Yes    |
| < 0.5   | ❌ No     |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: security@custos-core.dev (replace with your actual contact)

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
  
