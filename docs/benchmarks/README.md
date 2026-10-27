# Benchmarks

Latency and throughput receipts for the `/v1/evaluate` gate, so every
publicly cited performance claim is backed by a committed, re-runnable
artifact — same receipts discipline as the security records.

## Records

- `bench-oct24.json` — the benchmark cited publicly as "measured at 1.47ms
  p50" (hs256 sequential latency, p50 1.475ms / p95 1.679ms, 300 requests,
  zero errors, alternating ALLOW/DENY policy mix) and "1,122 rps"
  (16-worker concurrent throughput, 1122.3 rps, zero errors). Generated
  2026-10-25T01:00Z on a 4-vCPU Linux sandbox, single uvicorn replica,
  localhost keep-alive. rs256 mode results included in the same record.

## Reproduce

The harness is committed and self-contained:

```
python scripts/benchmark_evaluate.py --out results.json \
  --requests 300 --workers 16 --per-worker 100 --warmup 100
```

Numbers will vary with hardware; the committed record is the receipt for
the environment described inside it. The claim it backs is the
environment-matched one, not a hardware-independent guarantee.
