"""
CUSTOS Core -- FastAPI Runtime v1.0
Enterprise Release Candidate.

v1.0 additions:
- PostgreSQL audit backend support
- X-CUSTOS-Version response header on all endpoints
- /v1/info endpoint — version and backend info
- Kubernetes-ready health and readiness probes
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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
    TenantListResponse,
    TenantRegisterRequest,
    TenantResponse,
)
from custos.policy_diff import PolicyDiffer
from custos.policy_engine import PolicyAction, PolicyResult, PolicyRule
from custos.rate_limiter import QuotaConfig
from custos.replay import ReplayEngine
from custos.snapshot import SnapshotEngine
from custos.tenant import TenantConfig, TenantManager
from custos.tracing import tracer
from custos.validation import InputValidator

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger("main")

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
tenant_manager = TenantManager()
validator = InputValidator()
policy_differ = PolicyDiffer()

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
    logger.info("custos.startup", extra={"version": VERSION})
    yield
    logger.info("custos.shutdown")


app = FastAPI(
    title="CUSTOS Core",
    description="Policy-Governed AI Execution Firewall",
    version=VERSION,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Version header middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_version_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-CUSTOS-Version"] = VERSION
    return response


# ---------------------------------------------------------------------------
# Health / Ready / Metrics / Info
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        uptime_seconds=round(time.time() - _metrics["custos_uptime_start"], 1),
    )


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    try:
        default_ctx = tenant_manager.get("default")
        checks = {
            "policy_engine": default_ctx is not None and default_ctx.policy_engine.rule_count > 0,
            "rate_limiter": True,
            "audit_chain": default_ctx is not None,
            "tenant_manager": tenant_manager.count > 0,
        }
    except Exception as exc:
        logger.warning("ready.check_failed", extra={"error": str(exc)})
        checks = {
            "policy_engine": False,
            "rate_limiter": False,
            "audit_chain": False,
            "tenant_manager": False,
        }
    all_ready = all(checks.values())
    return ReadyResponse(
        status="ready" if all_ready else "not_ready",
        checks={k: "ok" if v else "fail" for k, v in checks.items()},
    )


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    uptime = round(time.time() - _metrics["custos_uptime_start"], 1)
    default_ctx = tenant_manager.get("default")
    audit_length = default_ctx.audit_chain.length if default_ctx else 0
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
        "# HELP custos_audit_chain_length Total audit records (default tenant)",
        "# TYPE custos_audit_chain_length gauge",
        f"custos_audit_chain_length {audit_length}",
        "# HELP custos_tenant_count Registered tenants",
        "# TYPE custos_tenant_count gauge",
        f"custos_tenant_count {tenant_manager.count}",
        "# HELP custos_uptime_seconds Seconds since startup",
        "# TYPE custos_uptime_seconds gauge",
        f"custos_uptime_seconds {uptime}",
    ]
    return "\n".join(lines) + "\n"


@app.get("/v1/info")
async def info():
    """Version and backend information."""
    default_ctx = tenant_manager.get("default")
    return {
        "version": VERSION,
        "audit_backend": default_ctx.audit_chain.backend_type,
        "tenant_count": tenant_manager.count,
        "uptime_seconds": round(
            time.time() - _metrics["custos_uptime_start"], 1
        ),
    }


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

@app.post("/v1/evaluate", response_model=EvaluateResponse)
async def evaluate(
    req: EvaluateRequest,
    _auth: Optional[str] = Depends(optional_auth),
):
    span = tracer.start_span("custos.evaluate")
    span.set_attribute("client_id", req.client_id)
    span.set_attribute("tenant_id", req.tenant_id)
    _metrics["custos_requests_total"] += 1

    val = validator.validate_request(req.client_id, req.content, req.token_count)
    if not val.valid:
        span.set_status("ERROR")
        tracer.finish_span(span)
        raise HTTPException(status_code=422, detail=val.error)

    ctx = tenant_manager.get_or_default(req.tenant_id)
    rate_key = (
        f"{req.tenant_id}:{req.client_id}"
        if req.tenant_id != "default"
        else req.client_id
    )

    if ctx.rate_limiter.get_all_quotas().get(rate_key) is None:
        ctx.rate_limiter.register(
            rate_key,
            QuotaConfig(requests_per_minute=60, requests_per_hour=1000),
        )

    allowed, msg = ctx.rate_limiter.check_and_consume(rate_key, req.token_count)
    if not allowed:
        _metrics["custos_rate_limit_hits"] += 1
        ctx.audit_chain.record(
            req.client_id, "rate_limited", msg, req.content,
            trace_id=span.trace_id,
        )
        span.set_status("RATE_LIMITED")
        tracer.finish_span(span)
        raise HTTPException(status_code=429, detail=msg)

    result: PolicyResult = ctx.policy_engine.evaluate(req.content)

    if result.allowed:
        if result.action.value == "audit":
            _metrics["custos_requests_audited"] += 1
        else:
            _metrics["custos_requests_allowed"] += 1
    else:
        _metrics["custos_requests_denied"] += 1

    audit_entry = ctx.audit_chain.record(
        client_id=req.client_id,
        action=result.action.value,
        reason=result.reason,
        content=req.content,
        triggered_rule=result.triggered_rule,
        trace_id=span.trace_id,
    )

    span.set_attribute("action", result.action.value)
    span.set_attribute("audit_record_hash", audit_entry.record_hash)
    tracer.finish_span(span)

    logger.info("evaluate.complete", extra={
        "client_id": req.client_id,
        "tenant_id": req.tenant_id,
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
        tenant_id=req.tenant_id,
        audit_record_hash=audit_entry.record_hash,
        trace_id=span.trace_id,
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@app.get("/v1/audit", response_model=list[AuditRecordResponse])
async def get_audit_log(
    client_id: Optional[str] = None,
    tenant_id: str = "default",
):
    ctx = tenant_manager.get_or_default(tenant_id)
    return ctx.audit_chain.get_records(client_id=client_id)


@app.get("/v1/audit/verify")
async def verify_audit_chain(tenant_id: str = "default"):
    ctx = tenant_manager.get_or_default(tenant_id)
    valid, reason = ctx.audit_chain.verify()
    return {
        "valid": valid,
        "reason": reason,
        "chain_length": ctx.audit_chain.length,
        "tenant_id": tenant_id,
        "backend": ctx.audit_chain.backend_type,
    }


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

@app.get("/v1/audit/snapshot", response_model=SnapshotResponse)
async def get_snapshot(
    tenant_id: str = "default",
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
):
    ctx = tenant_manager.get_or_default(tenant_id)
    engine = SnapshotEngine(ctx.audit_chain)
    result = engine.generate(start_time=start_time, end_time=end_time)
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
    ctx = tenant_manager.get("default")
    engine = SnapshotEngine(ctx.audit_chain)
    valid, reason = engine.verify_snapshot(req.snapshot)
    return SnapshotVerifyResponse(valid=valid, reason=reason)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

@app.post("/v1/replay", response_model=ReplayResponse)
async def replay(req: ReplayRequest):
    ctx = tenant_manager.get_or_default(req.tenant_id)
    replay_engine = ReplayEngine(ctx.audit_chain, ctx.policy_engine)
    try:
        result = replay_engine.replay_by_hash(
            record_hash=req.record_hash,
            original_content=req.original_content,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    ctx.audit_chain.record(
        client_id="system",
        action="replay",
        reason=f"Replayed record {req.record_hash[:16]}...",
        content=req.original_content,
    )

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
# Policy Diff
# ---------------------------------------------------------------------------

@app.post("/v1/policy/diff", response_model=PolicyDiffResponse)
async def policy_diff(req: PolicyDiffRequest):
    ACTION_MAP = {
        "allow": PolicyAction.ALLOW,
        "deny": PolicyAction.DENY,
        "audit": PolicyAction.AUDIT,
    }
    try:
        current_rules = [
            PolicyRule(name=r.name, pattern=r.pattern,
                       action=ACTION_MAP[r.action], reason=r.reason)
            for r in req.current_rules
        ]
        proposed_rules = [
            PolicyRule(name=r.name, pattern=r.pattern,
                       action=ACTION_MAP[r.action], reason=r.reason)
            for r in req.proposed_rules
        ]
    except KeyError as e:
        raise HTTPException(status_code=422, detail=f"Invalid action: {e}")

    result = policy_differ.diff(req.content, current_rules, proposed_rules)
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
# Tenant Management
# ---------------------------------------------------------------------------

@app.post("/v1/tenants", response_model=TenantResponse)
async def register_tenant(req: TenantRegisterRequest):
    if req.tenant_id == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot re-register the default tenant"
        )
    if tenant_manager.get(req.tenant_id):
        raise HTTPException(
            status_code=409,
            detail=f"Tenant '{req.tenant_id}' already exists"
        )
    config = TenantConfig(
        tenant_id=req.tenant_id,
        quota=QuotaConfig(
            requests_per_minute=req.requests_per_minute,
            requests_per_hour=req.requests_per_hour,
            tokens_per_minute=req.tokens_per_minute,
        ),
    )
    tenant_manager.register(req.tenant_id, config)
    logger.info("tenant.registered", extra={"tenant_id": req.tenant_id})
    return TenantResponse(
        tenant_id=req.tenant_id,
        requests_per_minute=req.requests_per_minute,
        requests_per_hour=req.requests_per_hour,
        tokens_per_minute=req.tokens_per_minute,
    )


@app.get("/v1/tenants", response_model=TenantListResponse)
async def list_tenants():
    tenants = tenant_manager.list_tenants()
    return TenantListResponse(tenants=tenants, count=len(tenants))


@app.delete("/v1/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str):
    if tenant_id == "default":
        raise HTTPException(
            status_code=400, detail="Cannot delete the default tenant"
        )
    removed = tenant_manager.unregister(tenant_id)
    if not removed:
        raise HTTPException(
            status_code=404, detail=f"Tenant '{tenant_id}' not found"
        )
    logger.info("tenant.deleted", extra={"tenant_id": tenant_id})
    return {"deleted": True, "tenant_id": tenant_id}
