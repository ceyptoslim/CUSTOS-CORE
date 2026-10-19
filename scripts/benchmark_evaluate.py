#!/usr/bin/env python3
"""
Reproducible /v1/evaluate performance benchmark.

Measures the full production decision path — HTTP parse, JWT verification
(HS256 shared-secret and RS256/JWKS asymmetric), request validation, tenant
resolution, rate limiting, policy evaluation (ALLOW and DENY paths), and
tamper-evident audit recording — against a real uvicorn ASGI server.

Methodology (see docs/performance/benchmark-v1.md):

1. Start uvicorn (main:app) on 127.0.0.1 with mode-specific auth env.
2. Register a dedicated "bench" tenant with a large rate quota via the
   admin API, plus one deny rule so both governance verdicts are measured.
3. Warmup (default 100 requests, excluded from results).
4. Sequential phase: N requests (default 300, alternating allow/deny
   content), per-request latency captured.
5. Concurrent phase: W workers (default 16) x R requests each (default 100),
   wall-clock throughput plus per-request latency.
6. Emit a JSON record with environment metadata. All requests must return
   200 with a governance verdict (ALLOW or DENY); any HTTP error, timeout,
   or rate-limit (429) fails the benchmark.

Usage:
    python scripts/benchmark_evaluate.py [--out results.json]
        [--requests 300] [--workers 16] [--per-worker 100] [--warmup 100]

Notes:
* RS256 mode generates an explicit RSA-2048 keypair so server and client
  share deterministic key material (ephemeral dev keys would differ per
  process). This mirrors production: CUSTOS_JWT_PRIVATE_KEY is explicit.
* Numbers are environment-dependent (CPU, host contention). The record
  discloses the environment; the methodology is the reproducible part.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import httpx

ALLOW_CONTENT = "benchmark evaluate request: routine governance check payload"
DENY_CONTENT = "BENCHMARK-DENY sensitive payload for deny-path measurement"
TENANT = "bench"
CLIENT = "bench_client"
ADMIN = "bench_admin"
DENY_PATTERN = "BENCHMARK-DENY"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def percentile(sorted_latencies: List[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list (milliseconds)."""
    if not sorted_latencies:
        return float("nan")
    k = max(0, min(len(sorted_latencies) - 1, round(pct / 100 * len(sorted_latencies)) - 1))
    return sorted_latencies[k]


def stats_ms(latencies_ms: List[float]) -> Dict[str, Any]:
    s = sorted(latencies_ms)
    return {
        "n": len(s),
        "p50_ms": round(percentile(s, 50), 3),
        "p95_ms": round(percentile(s, 95), 3),
        "p99_ms": round(percentile(s, 99), 3),
        "max_ms": round(s[-1], 3) if s else None,
        "mean_ms": round(statistics.fmean(s), 3) if s else None,
    }


def wait_until_ready(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    with httpx.Client(base_url=f"http://127.0.0.1:{port}") as c:
        while time.time() < deadline:
            try:
                if c.get("/health", timeout=2.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
    raise RuntimeError(f"server on port {port} not ready within {timeout}s")


def start_server(port: int, env_extra: Dict[str, str]) -> subprocess.Popen:
    env = dict(os.environ)
    env.update(env_extra)
    proc = subprocess.Popen(  # noqa: S603 (fixed args, no shell)
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_until_ready(port)
    return proc


def setup_bench_tenant(port: int, token: str) -> None:
    """Register the bench tenant + deny rule via the admin API."""
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=f"http://127.0.0.1:{port}") as c:
        # maximum quotas the API allows (le=10_000/min, le=100_000/h):
        # total benchmark requests per mode stay well under the minute cap.
        r = c.post("/v1/tenants", headers=headers, json={
            "tenant_id": TENANT,
            "requests_per_minute": 10_000,
            "requests_per_hour": 100_000,
            "tokens_per_minute": 10_000_000,
        }, timeout=10.0)
        if r.status_code not in (200, 409):  # 409 = already exists (rerun)
            raise RuntimeError(f"tenant registration failed: {r.status_code} {r.text[:200]}")
        r = c.post(f"/v1/tenants/{TENANT}/policy", headers=headers, json={
            "name": "bench-deny",
            "pattern": DENY_PATTERN,
            "action": "deny",
            "reason": "benchmark deny-path rule",
        }, timeout=10.0)
        if r.status_code != 200:
            raise RuntimeError(f"policy rule failed: {r.status_code} {r.text[:200]}")


def make_client_token(mode: str, secret: str, private_key_pem: str) -> Tuple[str, str]:
    """Client token + admin token for the given mode."""
    import jwt

    now = int(time.time())
    if mode == "hs256":
        client = jwt.encode({"sub": CLIENT, "iat": now, "exp": now + 3600},
                            secret, algorithm="HS256")
        admin = jwt.encode({"sub": ADMIN, "iat": now, "exp": now + 3600},
                           secret, algorithm="HS256")
        return client, admin
    # rs256: derive kid from the JWKS the server publishes
    return "", ""


def make_rs256_tokens(port: int, private_key_pem: str) -> Tuple[str, str]:
    """RS256 tokens, with kid taken from the server's JWKS (discovery path)."""
    import jwt
    from cryptography.hazmat.primitives import serialization

    with httpx.Client(base_url=f"http://127.0.0.1:{port}") as c:
        jwk = c.get("/.well-known/jwks.json", timeout=10.0).json()["keys"][0]
    kid = jwk["kid"]
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    now = int(time.time())
    client = jwt.encode({"sub": CLIENT, "iat": now, "exp": now + 3600}, key,
                        algorithm="RS256", headers={"kid": kid})
    admin = jwt.encode({"sub": ADMIN, "iat": now, "exp": now + 3600}, key,
                       algorithm="RS256", headers={"kid": kid})
    return client, admin


def make_hs256_tokens(secret: str) -> Tuple[str, str]:
    import jwt

    now = int(time.time())
    return (
        jwt.encode({"sub": CLIENT, "iat": now, "exp": now + 3600}, secret, algorithm="HS256"),
        jwt.encode({"sub": ADMIN, "iat": now, "exp": now + 3600}, secret, algorithm="HS256"),
    )


# ---------------------------------------------------------------------------
# Measurement phases
# ---------------------------------------------------------------------------

def run_sequential(client: httpx.Client, token: str, n: int) -> Dict[str, Any]:
    latencies: List[float] = []
    verdicts = {"ALLOW": 0, "DENY": 0}
    errors = 0
    for i in range(n):
        content = DENY_CONTENT if i % 2 else ALLOW_CONTENT
        t0 = time.perf_counter_ns()
        r = client.post("/v1/evaluate", headers={"Authorization": f"Bearer {token}"},
                        json={"client_id": CLIENT, "tenant_id": TENANT,
                              "content": content, "token_count": 1})
        dt = (time.perf_counter_ns() - t0) / 1e6
        if r.status_code != 200:
            errors += 1
            continue
        verdicts[r.json().get("action", "?").upper()] = verdicts.get(
            r.json().get("action", "?").upper(), 0) + 1
        latencies.append(dt)
    return {"latency": stats_ms(latencies), "verdicts": verdicts, "errors": errors}


def run_concurrent(client: httpx.Client, token: str, workers: int,
                   per_worker: int) -> Dict[str, Any]:
    latencies: List[float] = []
    lock = threading.Lock()
    errors = 0
    verdicts: Dict[str, int] = {"ALLOW": 0, "DENY": 0}

    def worker(wid: int) -> None:
        nonlocal errors
        local: List[float] = []
        for i in range(per_worker):
            content = DENY_CONTENT if (wid + i) % 2 else ALLOW_CONTENT
            t0 = time.perf_counter_ns()
            r = client.post("/v1/evaluate",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"client_id": CLIENT, "tenant_id": TENANT,
                                  "content": content, "token_count": 1})
            dt = (time.perf_counter_ns() - t0) / 1e6
            if r.status_code != 200:
                with lock:
                    errors += 1
                continue
            local.append(dt)
            v = r.json().get("action", "?").upper()
            with lock:
                verdicts[v] = verdicts.get(v, 0) + 1
        with lock:
            latencies.extend(local)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(workers)]
    t0 = time.perf_counter_ns()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall_s = (time.perf_counter_ns() - t0) / 1e9
    total = workers * per_worker
    return {
        "workers": workers,
        "requests": total,
        "wall_seconds": round(wall_s, 3),
        "throughput_rps": round(total / wall_s, 1),
        "latency": stats_ms(latencies),
        "verdicts": verdicts,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="benchmark-results.json")
    ap.add_argument("--requests", type=int, default=300)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--per-worker", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--base-port", type=int, default=8210)
    args = ap.parse_args()

    # explicit RSA key for RS256 mode (deterministic across processes)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    hs_secret = "benchmark-secret-0123456789abcdef"  # 32+ bytes

    modes = {
        "hs256": {"port": args.base_port, "env": {
            "CUSTOS_JWT_ALGORITHM": "HS256", "CUSTOS_JWT_SECRET": hs_secret}},
        "rs256": {"port": args.base_port + 1, "env": {
            "CUSTOS_JWT_ALGORITHM": "RS256", "CUSTOS_JWT_PRIVATE_KEY": pem}},
    }

    record: Dict[str, Any] = {
        "benchmark_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "server": "uvicorn (localhost, single replica, keep-alive)",
        },
        "config": {
            "warmup_requests": args.warmup,
            "sequential_requests": args.requests,
            "concurrent_workers": args.workers,
            "requests_per_worker": args.per_worker,
            "content_mix": "alternating ALLOW/DENY policy match",
        },
        "modes": {},
    }

    for mode, cfg in modes.items():
        port = cfg["port"]
        print(f"[{mode}] starting server on 127.0.0.1:{port} ...")
        proc = start_server(port, cfg["env"])
        try:
            if mode == "hs256":
                client_token, admin_token = make_hs256_tokens(hs_secret)
            else:
                client_token, admin_token = make_rs256_tokens(port, pem)
            setup_bench_tenant(port, admin_token)

            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15.0) as c:
                # warmup (excluded)
                for i in range(args.warmup):
                    content = DENY_CONTENT if i % 2 else ALLOW_CONTENT
                    r = c.post("/v1/evaluate",
                               headers={"Authorization": f"Bearer {client_token}"},
                               json={"client_id": CLIENT, "tenant_id": TENANT,
                                     "content": content, "token_count": 1})
                    if r.status_code != 200:
                        raise RuntimeError(f"warmup failed: {r.status_code}")

                print(f"[{mode}] sequential phase ({args.requests} requests) ...")
                seq = run_sequential(c, client_token, args.requests)
                print(f"[{mode}] concurrent phase "
                      f"({args.workers}x{args.per_worker}) ...")
                conc = run_concurrent(c, client_token, args.workers, args.per_worker)

            ok = seq["errors"] == 0 and conc["errors"] == 0
            record["modes"][mode] = {
                "auth": mode,
                "sequential": seq,
                "concurrent": conc,
                "all_requests_ok": ok,
            }
            print(f"[{mode}] p50={seq['latency']['p50_ms']}ms "
                  f"p99={seq['latency']['p99_ms']}ms "
                  f"rps={conc['throughput_rps']} errors={seq['errors'] + conc['errors']}")
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    print(f"record written: {args.out}")

    all_ok = all(m["all_requests_ok"] for m in record["modes"].values())
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
