# CUSTOS-CORE Licensing

## Open Source Core — AGPL-3.0

CUSTOS-CORE is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0).

This means:
- ✅ You can use, modify, and distribute the code
- ✅ You can deploy it internally
- ❌ If you deploy it as a **network service** (SaaS, API, cloud), you MUST open-source all modifications
- ❌ You cannot rebrand and sell it as a closed-source product

### Why AGPL-3.0?

AGPL-3.0 closes the "SaaS loophole" that Apache 2.0 and MIT leave open.
Without AGPL, a competitor could fork this repo, build a hosted service,
and never contribute back. With AGPL, anyone who deploys as a service
must share their changes with the community.

### Commercial License

For organizations that want to use CUSTOS-CORE without AGPL obligations
(no open-sourcing required), a commercial license is available.

Contact: FroLife Productions

---

## What's Open Source (AGPL-3.0)

The following components are in this public repository and licensed under AGPL-3.0:

| Component | Status |
|-----------|--------|
| /v1/evaluate policy decision API | Open Source |
| Regex-based policy engine | Open Source |
| JWT authentication (HS256) | Open Source |
| Rate limiting | Open Source |
| Hash-chained audit trail | Open Source |
| Input validation | Open Source |
| Tenant manager | Open Source |
| SQLite audit backend | Open Source |
| Docker deployment | Open Source |
| OPA hybrid policy engine | Open Source |
| OPA pure mode (fail-closed) | Open Source |
| Hybrid mode (graceful fallback) | Open Source |

---

## OPA Failure Semantics — Critical Documentation

The two OPA modes have **materially different failure semantics**. This must be
understood before selecting a production deployment mode.

### Pure OPA Mode (`CUSTOS_POLICY_ENGINE=opa`)

**Fail-closed.** If the OPA server is unavailable, CUSTOS returns DENY for
all requests — including clean content. This is the restrictive, secure default.

Use this when: OPA is part of the authoritative production security boundary
and you would rather block everything than allow something without policy review.

### Hybrid Mode (`CUSTOS_POLICY_ENGINE=hybrid`)

**Graceful fallback to regex.** If the OPA server is unavailable, CUSTOS
preserves the local regex engine's decision. The regex engine always runs
first; OPA only runs as a second-pass for content the regex engine allowed.

Use this when: availability is prioritized and the regex engine is an
acceptable emergency enforcement layer.

**Hybrid does NOT fail closed.** A request that the regex engine allows
will be allowed even if OPA is unreachable. This is by design — the regex
engine provides baseline protection (SSN, credit cards, prompt injection)
without any external dependency.

### Decision Matrix

| Scenario | Pure OPA | Hybrid |
|----------|----------|--------|
| OPA healthy, content clean | ALLOW | ALLOW |
| OPA healthy, content violates | DENY | DENY |
| OPA healthy, custom tenant rule | DENY | DENY |
| OPA down, content clean | **DENY** | ALLOW (regex) |
| OPA down, content violates regex | **DENY** | DENY (regex) |
| OPA returns malformed response | **DENY** | regex result (fallback) |
| OPA down, content is clean | **DENY** | ALLOW (regex) |

### Deployment Recommendation

- If OPA is part of your authoritative production security boundary → use `opa`
- If availability is prioritized and regex is acceptable as emergency enforcement → use `hybrid`
- If you have no OPA server → use `regex` (default, no external dependency)
| Rego policy definitions | Open Source |
| Policy factory (regex/opa/hybrid) | Open Source |
| CI pipeline (ruff, bandit, pip-audit, OPA integration) | Open Source |
| Test suite (329 tests) | Open Source |

---

## What's Commercial (Private — Not on GitHub)

The following are proprietary, maintained in private Base44 applications:

| Component | Location |
|-----------|----------|
| /v1/execute enforcement firewall | Private repo (planned) |
| SSRF DNS-rebinding protection | Private repo (planned) |
| Per-target circuit breaker | Private repo (planned) |
| Production fail-closed auth | Private repo (planned) |
| Tenant authorization binding | Private repo (planned) |
| PostgreSQL audit backend | Private repo (planned) |
| OTLP/OpenTelemetry tracing | Private repo (planned) |
| Kubernetes/Helm deployment | Private repo (planned) |
| Policy diff/replay/snapshot | Private repo (planned) |
| Multi-tenant policy persistence | Private repo (planned) |

**Base44 Applications (already private):**

| Application | Purpose |
|-------------|---------|
| CUSTOS-CORE Media Bridge | Media governance dashboard, YouTube management |
| QueryForge | Business ops, CRM, policy management, agent registry |
| InsightFlow | Audit logging, YouTube upload workflow, credential management |
| DeployFlow | Deployment platform, template/plugin marketplace |

---

## Trademark Notice

"CUSTOS", "CUSTOS-CORE", "LORL", and "LORL-9.1" are product names of
FroLife Productions. The open-source license covers the code, not the brand.
You may not use these names to endorse or promote derived products without
written permission.

---

## Contributor License Agreement (CLA)

All contributors must agree to the CLA before contributions are accepted.
The CLA ensures that CUSTOS-CORE can offer a commercial dual-license.

By contributing, you grant FroLife Productions a perpetual, worldwide,
non-exclusive, royalty-free license to use, modify, and distribute your
contribution under both the AGPL-3.0 and a commercial license.

This allows us to:
1. Keep the open-source version under AGPL
2. Offer a commercial license to enterprise customers
3. Protect the project from being locked down by a single contributor

---

## Summary

```
┌─────────────────────────────────────────────────┐
│  PUBLIC (GitHub — AGPL-3.0)                     │
│  ┌─────────────────────────────────────────┐    │
│  │ CUSTOS-CORE: Policy engine, evaluate    │    │
│  │ API, JWT auth, rate limiting, audit     │    │
│  │ chain, OPA hybrid, tests, CI            │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │ LORL-9.1: Agents, event ledger,         │    │
│  │ identity, treaty engine, OPA client     │    │
│  └─────────────────────────────────────────┘    │
├─────────────────────────────────────────────────┤
│  PRIVATE (Base44 apps + enterprise repo)        │
│  ┌─────────────────────────────────────────┐    │
│  │ Enterprise: /v1/execute, SSRF, K8s,    │    │
│  │ PostgreSQL, OTLP, circuit breaker,      │    │
│  │ tenant binding, fail-closed auth        │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │ Commercial apps: Media Bridge,          │    │
│  │ QueryForge, InsightFlow, DeployFlow    │    │
│  └─────────────────────────────────────────┘    │
├─────────────────────────────────────────────────┤
│  PROTECTED (Trademark + CLA)                    │
│  "CUSTOS" "CUSTOS-CORE" "LORL" brand names     │
│  Contributor License Agreement for all PRs      │
└─────────────────────────────────────────────────┘
```
