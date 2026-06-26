"""
CUSTOS Core -- FastAPI Runtime v0.3
Exposes: POST /v1/evaluate, GET /health, GET /ready, GET /metrics, GET /v1/audit

v0.3 additions:
- Structured JSON logging on every request
- OpenTelemetry-compatible span on /v1/evaluate
- Trace ID returned in EvaluateResponse and stored in audit chain
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from custos.audit import AuditChain
from custos.auth import verify_token
from custos.logging import configure_logging, get_logger
from custos.models import (
    AuditRecordResponse,
    EvaluateRequest,
    EvaluateResponse,
    HealthResponse,
    ReadyResponse,
)
from custos.policy_engine import PolicyEngine, PolicyResult
from custos.rate_limiter import QuotaConfig, RateLimiter
from custos.tracing import tracer
from custos.validation import InputValidator

# ---------------------------------------------------------------------------
# Logging — configure at import time
# ---------------------------------------------------------------------------
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger("main")

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
policy_engine = PolicyEngine()
rate_limiter = RateLimiter()
audit_chain = AuditChain()
validator = InputValidator()

rate_limiter.register(
    "default",
    QuotaConfig(requests_per_minute=60, requests_per_hour=1000, tokens_per_minute=100_000),
)

# ---------------------------------------------------------------------------
# Metrics counters
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
# Auth
# ---------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False)


async def optional_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[str]:
    if os.getenv("AUTH_DISABLED", "0") == "1":
        return None
    return verify_token(credentials)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("custos.startup", extra={"version": "0.3.0"})
    yield
    logger.info("custos.shutdown")


app = FastAPI(
    title="CUSTOS Core",
    description="Policy-Governed AI Execution Firewall",
    version="0.3.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        uptime_seconds=round(time.time() - _metrics["custos_uptime_start"], 1),
    )


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    checks = {
        "policy_engine": policy_engine.rule_count > 0,
        "rate_limiter": True,
        "audit_chain": True,
    }
    all_ready = all(checks.values())
    return ReadyResponse(
        status="ready" if all_ready else "not_ready",
        checks={k: "ok" if v else "fail" for k, v in checks.items()},
    )


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
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
        "# HELP custos_requests_audited Requests flagged for audit",
        "# TYPE custos_requests_audited counter",
        f"custos_requests_audited {_metrics['custos_requests_audited']}",
        "# HELP custos_rate_limit_hits Requests rejected by rate limiter",
        "# TYPE custos_rate_limit_hits counter",
        f"custos_rate_limit_hits {_metrics['custos_rate_limit_hits']}",
        "# HELP custos_audit_chain_length Total audit records",
        "# TYPE custos_audit_chain_length gauge",
        f"custos_audit_chain_length {audit_chain.length}",
        "# HELP custos_uptime_seconds Seconds since startup",
        "# TYPE custos_uptime_seconds gauge",
        f"custos_uptime_seconds {uptime}",
    ]
    return "\n".join(lines) + "\n"


@app.post("/v1/evaluate", response_model=EvaluateResponse)
async def evaluate(
    req: EvaluateRequest,
    _auth: Optional[str] = Depends(optional_auth),
):
    span = tracer.start_span("custos.evaluate")
    span.set_attribute("client_id", req.client_id)

    _metrics["custos_requests_total"] += 1

    # Validation
    val = validator.validate_request(req.client_id, req.content, req.token_count)
    if not val.valid:
        span.set_status("ERROR")
        tracer.finish_span(span)
        logger.warning(
            "evaluate.validation_failed",
            extra={"client_id": req.client_id, "error": val.error,
                   "trace_id": span.trace_id},
        )
        raise HTTPException(status_code=422, detail=val.error)

    # Rate limiter
    allowed, msg = rate_limiter.check_and_consume(req.client_id, req.token_count)
    if not allowed:
        _metrics["custos_rate_limit_hits"] += 1
        audit_chain.record(req.client_id, "rate_limited", msg, req.content,
                          trace_id=span.trace_id)
        span.set_status("RATE_LIMITED")
        tracer.finish_span(span)
        logger.warning(
            "evaluate.rate_limited",
            extra={"client_id": req.client_id, "trace_id": span.trace_id},
        )
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

    # Audit chain — includes trace_id for correlation
    audit_entry = audit_chain.record(
        client_id=req.client_id,
        action=result.action.value,
        reason=result.reason,
        content=req.content,
        triggered_rule=result.triggered_rule,
        trace_id=span.trace_id,
    )

    # Finish span with full context
    span.set_attribute("action", result.action.value)
    span.set_attribute("triggered_rule", result.triggered_rule)
    span.set_attribute("audit_record_hash", audit_entry.record_hash)
    span.set_attribute("allowed", result.allowed)
    tracer.finish_span(span)

    logger.info(
        "evaluate.complete",
        extra={
            "client_id": req.client_id,
            "action": result.action.value,
            "triggered_rule": result.triggered_rule,
            "allowed": result.allowed,
            "trace_id": span.trace_id,
            "audit_record_hash": audit_entry.record_hash,
        },
    )

    return EvaluateResponse(
        allowed=result.allowed,
        action=result.action.value,
        triggered_rule=result.triggered_rule,
        reason=result.reason,
        client_id=req.client_id,
        audit_record_hash=audit_entry.record_hash,
        trace_id=span.trace_id,
    )


@app.get("/v1/audit", response_model=list[AuditRecordResponse])
async def get_audit_log(client_id: str = None):
    return audit_chain.get_records(client_id=client_id)


@app.get("/v1/audit/verify")
async def verify_audit_chain():
    valid, reason = audit_chain.verify()
    return {"valid": valid, "reason": reason, "chain_length": audit_chain.length}
