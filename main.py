"""
CUSTOS Core -- FastAPI Runtime v0.4
Exposes all v0.3 endpoints plus:
- POST /v1/replay
- POST /v1/policy/diff
- GET  /v1/audit/snapshot
- POST /v1/audit/snapshot/verify
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
    PolicyDiffRequest,
    PolicyDiffResponse,
    ReadyResponse,
    ReplayRequest,
    ReplayResponse,
    SnapshotResponse,
    SnapshotVerifyRequest,
    SnapshotVerifyResponse,
)
from custos.policy_diff import PolicyDiffer
from custos.policy_engine import PolicyAction, PolicyEngine, PolicyResult, PolicyRule
from custos.rate_limiter import QuotaConfig, RateLimiter
from custos.replay import ReplayEngine
from custos.snapshot import SnapshotEngine
from custos.tracing import tracer
from custos.validation import InputValidator

# ---------------------------------------------------------------------------
# Logging
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
replay_engine = ReplayEngine(audit_chain, policy_engine)
snapshot_engine = SnapshotEngine(audit_chain)
policy_differ = PolicyDiffer()

rate_limiter.register(
    "default",
    QuotaConfig(requests_per_minute=60, requests_per_hour=1000, tokens_per_minute=100_000),
)

# ---------------------------------------------------------------------------
# Metrics
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
    logger.info("custos.startup", extra={"version": "0.4.0"})
    yield
    logger.info("custos.shutdown")


app = FastAPI(
    title="CUSTOS Core",
    description="Policy-Governed AI Execution Firewall",
    version="0.4.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Existing routes (unchanged from v0.3)
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

    val = validator.validate_request(req.client_id, req.content, req.token_count)
    if not val.valid:
        span.set_status("ERROR")
        tracer.finish_span(span)
        raise HTTPException(status_code=422, detail=val.error)

    allowed, msg = rate_limiter.check_and_consume(req.client_id, req.token_count)
    if not allowed:
        _metrics["custos_rate_limit_hits"] += 1
        audit_chain.record(req.client_id, "rate_limited", msg, req.content,
                           trace_id=span.trace_id)
        span.set_status("RATE_LIMITED")
        tracer.finish_span(span)
        raise HTTPException(status_code=429, detail=msg)

    result: PolicyResult = policy_engine.evaluate(req.content)

    if result.allowed:
        if result.action.value == "audit":
            _metrics["custos_requests_audited"] += 1
        else:
            _metrics["custos_requests_allowed"] += 1
    else:
        _metrics["custos_requests_denied"] += 1

    audit_entry = audit_chain.record(
        client_id=req.client_id,
        action=result.action.value,
        reason=result.reason,
        content=req.content,
        triggered_rule=result.triggered_rule,
        trace_id=span.trace_id,
    )

    span.set_attribute("action", result.action.value)
    span.set_attribute("audit_record_hash", audit_entry.record_hash)
    span.set_attribute("allowed", result.allowed)
    tracer.finish_span(span)

    logger.info("evaluate.complete", extra={
        "client_id": req.client_id,
        "action": result.action.value,
        "allowed": result.allowed,
        "trace_id": span.trace_id,
    })

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


# ---------------------------------------------------------------------------
# v0.4 — Replay Engine
# ---------------------------------------------------------------------------

@app.post("/v1/replay", response_model=ReplayResponse)
async def replay(req: ReplayRequest):
    """
    Reproduce a past policy decision given its audit record hash
    and the original content string.
    """
    try:
        result = replay_engine.replay_by_hash(
            record_hash=req.record_hash,
            original_content=req.original_content,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Record the replay itself in the audit chain
    audit_chain.record(
        client_id="system",
        action="replay",
        reason=f"Replayed record {req.record_hash[:16]}...",
        content=req.original_content,
    )

    logger.info("replay.complete", extra={
        "record_hash": req.record_hash,
        "decision_matches": result.decision_matches,
    })

    return ReplayResponse(
        original_record_hash=result.original_record_hash,
        original_timestamp=result.original_timestamp,
        original_action=result.original_action,
        original_triggered_rule=result.original_triggered_rule,
        original_trace_id=result.original_trace_id,
        replayed_action=result.replayed_action,
        replayed_triggered_rule=result.replayed_triggered_rule,
        replayed_reason=result.replayed_reason,
        decision_matches=result.decision_matches,
        replay_timestamp=result.replay_timestamp,
        content_hash=result.content_hash,
    )


# ---------------------------------------------------------------------------
# v0.4 — Policy Diff
# ---------------------------------------------------------------------------

@app.post("/v1/policy/diff", response_model=PolicyDiffResponse)
async def policy_diff(req: PolicyDiffRequest):
    """
    Compare how a piece of content would be evaluated under
    two different policy rule sets.
    """
    ACTION_MAP = {
        "allow": PolicyAction.ALLOW,
        "deny": PolicyAction.DENY,
        "audit": PolicyAction.AUDIT,
    }

    try:
        current_rules = [
            PolicyRule(
                name=r.name,
                pattern=r.pattern,
                action=ACTION_MAP[r.action],
                reason=r.reason,
            )
            for r in req.current_rules
        ]
        proposed_rules = [
            PolicyRule(
                name=r.name,
                pattern=r.pattern,
                action=ACTION_MAP[r.action],
                reason=r.reason,
            )
            for r in req.proposed_rules
        ]
    except KeyError as e:
        raise HTTPException(status_code=422, detail=f"Invalid action: {e}")

    result = policy_differ.diff(req.content, current_rules, proposed_rules)

    logger.info("policy_diff.complete", extra={
        "decision_changed": result.decision_changed,
        "change_summary": result.change_summary,
    })

    return PolicyDiffResponse(
        content_preview=result.content_preview,
        current_action=result.current_action,
        current_triggered_rule=result.current_triggered_rule,
        current_reason=result.current_reason,
        proposed_action=result.proposed_action,
        proposed_triggered_rule=result.proposed_triggered_rule,
        proposed_reason=result.proposed_reason,
        decision_changed=result.decision_changed,
        change_summary=result.change_summary,
    )


# ---------------------------------------------------------------------------
# v0.4 — Decision Snapshots
# ---------------------------------------------------------------------------

@app.get("/v1/audit/snapshot", response_model=SnapshotResponse)
async def get_snapshot(
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
):
    """
    Export a tamper-evident snapshot of the audit chain
    for the given time range.
    """
    result = snapshot_engine.generate(start_time=start_time, end_time=end_time)
    logger.info("snapshot.generated", extra={
        "record_count": result.record_count,
        "chain_valid": result.chain_valid,
    })
    return SnapshotResponse(
        generated_at=result.generated_at,
        start_time=result.start_time,
        end_time=result.end_time,
        record_count=result.record_count,
        records=result.records,
        chain_valid=result.chain_valid,
        chain_verification_reason=result.chain_verification_reason,
        latest_hash=result.latest_hash,
        snapshot_hash=result.snapshot_hash,
    )


@app.post("/v1/audit/snapshot/verify", response_model=SnapshotVerifyResponse)
async def verify_snapshot(req: SnapshotVerifyRequest):
    """Verify the integrity of a previously generated snapshot."""
    valid, reason = snapshot_engine.verify_snapshot(req.snapshot)
    return SnapshotVerifyResponse(valid=valid, reason=reason)
