"""
CUSTOS Core — FastAPI Runtime
Exposes: POST /v1/evaluate, GET /health, GET /metrics
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from custos.policy_engine import PolicyEngine, PolicyResult
from custos.rate_limiter import QuotaConfig, RateLimiter

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
policy_engine = PolicyEngine()
rate_limiter = RateLimiter()

# Register a default client for demo/testing
rate_limiter.register(
    "default",
    QuotaConfig(requests_per_minute=60, requests_per_hour=1000, tokens_per_minute=100_000),
)

# ---------------------------------------------------------------------------
# Prometheus-style metrics (simple counters, no external dependency)
# ---------------------------------------------------------------------------
_metrics = {
    "custos_requests_total": 0,
    "custos_requests_allowed": 0,
    "custos_requests_denied": 0,
    "custos_requests_audited": 0,
    "custos_rate_limit_hits": 0,
    "custos_uptime_start": time.time(),
}


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # startup / shutdown hooks go here


app = FastAPI(
    title="CUSTOS Core",
    description="AI Governance & Compliance Firewall",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class EvaluateRequest(BaseModel):
    client_id: str = "default"
    content: str
    token_count: int = 1


class EvaluateResponse(BaseModel):
    allowed: bool
    action: str
    triggered_rule: str | None
    reason: str
    client_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "uptime_seconds": round(time.time() - _metrics["custos_uptime_start"], 1)}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus-compatible text exposition format."""
    uptime = round(time.time() - _metrics["custos_uptime_start"], 1)
    lines = [
        "# HELP custos_requests_total Total requests evaluated",
        "# TYPE custos_requests_total counter",
        f"custos_requests_total {_metrics['custos_requests_total']}",
        "# HELP custos_requests_allowed Requests allowed",
        "# TYPE custos_requests_allowed counter",
        f"custos_requests_allowed {_metrics['custos_requests_allowed']}",
        "# HELP custos_requests_denied Requests denied by policy",
        "# TYPE custos_requests_denied counter",
        f"custos_requests_denied {_metrics['custos_requests_denied']}",
        "# HELP custos_requests_audited Requests allowed but flagged for audit",
        "# TYPE custos_requests_audited counter",
        f"custos_requests_audited {_metrics['custos_requests_audited']}",
        "# HELP custos_rate_limit_hits Requests rejected by rate limiter",
        "# TYPE custos_rate_limit_hits counter",
        f"custos_rate_limit_hits {_metrics['custos_rate_limit_hits']}",
        "# HELP custos_uptime_seconds Seconds since startup",
        "# TYPE custos_uptime_seconds gauge",
        f"custos_uptime_seconds {uptime}",
    ]
    return "\n".join(lines) + "\n"


@app.post("/v1/evaluate", response_model=EvaluateResponse)
async def evaluate(req: EvaluateRequest):
    _metrics["custos_requests_total"] += 1

    # Rate limiter check
    allowed, msg = rate_limiter.check_and_consume(req.client_id, req.token_count)
    if not allowed:
        _metrics["custos_rate_limit_hits"] += 1
        raise HTTPException(status_code=429, detail=msg)

    # Policy evaluation
    result: PolicyResult = policy_engine.evaluate(req.content)

    if result.allowed:
        if result.action.value == "audit":
            _metrics["custos_requests_audited"] += 1
        else:
            _metrics["custos_requests_allowed"] += 1
    else:
        _metrics["custos_requests_denied"] += 1

    return EvaluateResponse(
        allowed=result.allowed,
        action=result.action.value,
        triggered_rule=result.triggered_rule,
        reason=result.reason,
        client_id=req.client_id,
    )
