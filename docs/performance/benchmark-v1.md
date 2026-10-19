# /v1/evaluate Performance Benchmark (v1)

Reproducible measurement of the full production decision path: HTTP parse,
JWT verification, request validation, tenant resolution, rate limiting,
policy evaluation (ALLOW and DENY paths), and tamper-evident audit recording.

## How to run

```bash
python scripts/benchmark_evaluate.py --out results.json
```

Defaults: 100 warmup, 300 sequential, 16 workers x 100 concurrent requests,
alternating ALLOW/DENY policy matches, per auth mode (HS256 and RS256).
A dedicated `bench` tenant is registered via the admin API with maximum
quotas; one deny rule is added so both governance verdicts are measured.
Any HTTP error, timeout, or rate-limit (429) fails the run.

## Methodology

- Real ASGI server: uvicorn on 127.0.0.1, one replica, keep-alive client.
- RS256 mode uses an explicit RSA-2048 keypair (same material client + server,
  mirroring production `CUSTOS_JWT_PRIVATE_KEY`); the token `kid` is taken
  from the server's `/.well-known/jwks.json` discovery endpoint.
- Warmup excluded. Per-request latency via `perf_counter_ns`.
- Percentiles: nearest-rank over sorted latencies (milliseconds).

## Baseline results (this methodology's first recorded run)

Environment: shared 4-vCPU container, Python 3.11, single replica, localhost.
Numbers are environment-dependent; the reproducible part is the methodology.

| Mode | p50 | p95 | p99 | max | Throughput (16 workers) |
|---|---|---|---|---|---|
| HS256 | 1.47 ms | 1.73 ms | 1.94 ms | 2.18 ms | 1,166 req/s |
| RS256 | 1.61 ms | 1.85 ms | 1.93 ms | 2.24 ms | 1,046 req/s |

Verified across two consecutive runs (second run: HS256 p99 1.77 ms,
RS256 p99 2.10 ms — stable within measurement noise). Verdict mix per mode:
exactly 150 ALLOW + 150 DENY sequential, zero errors, zero 429s.

### Reading the numbers

- **Governance overhead is ~1.5 ms p50 end-to-end**: every request passes
  auth verification, validation, rate limiting, policy evaluation, and a
  tamper-evident audit-chain record (SHA-256 chained) before the response.
- **The RS256/JWKS production upgrade costs ~0.13 ms p50 (~9%)** relative to
  shared-secret HS256 — asymmetric verification is production-viable at
  negligible marginal latency.
- **Throughput > 1,000 req/s per replica** in a modest container; horizontal
  scaling is per the deployment model (rate limiting per replica until the
  distributed limiter focus item ships).

## Bug found and fixed by this benchmark

The benchmark initially received 429s at request 61 despite registering the
tenant with a 10,000/minute quota: the `/v1/evaluate` auto-registration for
new per-client rate keys used a hardcoded 60/minute quota, silently ignoring
the tenant API's `requests_per_minute` contract. Fixed: new rate keys now
inherit the tenant's configured quota (`RateLimiter.get_quota`), with the
conservative 60/minute default retained only for tenants without explicit
configuration (behavior of the default tenant unchanged). Regression tests:
`TestTenantQuotaInheritance` in `tests/test_api.py`.
