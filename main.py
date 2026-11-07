"""
CUSTOS Core -- FastAPI Runtime v1.1

v1.1 additions:
- Tenant policy rules persist across restarts via PolicyStore
  (POST/GET /v1/tenants/{tenant_id}/policy), closing issue #20
- OTLP trace export to a real collector via OTEL_EXPORTER_OTLP_ENDPOINT,
  closing issue #21 (see custos/tracing.py)

v1.0 additions:
- PostgreSQL audit backend support
- X-CUSTOS-Version response header on all endpoints
- /v1/info endpoint — version and backend info
- Kubernetes-ready health and readiness probes
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.



import hmac
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from custos.audit_persistence import (
    AuditPersistenceRefused,
    audit_store_source,
    is_durable,
    require_durable_audit,
)
from custos.auth import validate_production_secrets, auth_enabled, verify_token
from custos.content_retention import (
    ADMIN_TOKEN_ENV,
    MODE_OFF,
    MODE_ENV,
    RetentionConfigRefused,
    admin_token,
    content_retention_mode,
    content_store_for,
    store_directory,
    store_path_for,
    validate_content_retention,
)
from custos.retention import (
    STATUS_PURGED,
    STATUS_UNKNOWN,
    ContentPurged,
    record_decision,
    PurgeRefused,
    reconcile,
)
from custos.jwks import get_jwks_document, validate_production_key
from custos.logging import configure_logging, get_logger
from custos.audit import AuditStoreFull, COMMITMENT_NONE
from custos.policy_citation import content_engine_digest
from custos.models import (
    AuditRecordResponse,
    EvaluateActionRequest,
    EvaluateRequest,
    EvaluateResponse,
    HealthResponse,
    PolicyDiffRequest,
    PolicyDiffResponse,
    PolicyRuleAddResponse,
    PolicyRuleListResponse,
    PolicyRuleRequest,
    ReadyResponse,
    ReplayRequest,
    ReplayResponse,
    RetentionFinding,
    RetentionPurgeRequest,
    RetentionPurgeResponse,
    RetentionStatusResponse,
    SnapshotResponse,
    SnapshotVerifyRequest,
    SnapshotVerifyResponse,
    TenantListResponse,
    TenantRegisterRequest,
    TenantResponse,
)
from custos.policy_diff import PolicyDiffer
from custos.policy_engine import PolicyAction, PolicyResult, PolicyRule
from custos.policy_store import PolicyStore
from custos.rate_limiter import QuotaConfig
from custos.replay import ReplayEngine
from custos.snapshot import SnapshotEngine
from custos.scaling import validate_replica_configuration
from custos.tenant import TenantConfig, TenantManager
from custos.action_gate import ActionGate, ActionRequest
from custos.tracing import tracer
from custos.execution import HTTPExecutionAdapter
from custos.validation import InputValidator
from custos.custody import AnchorManager, build_custody_from_env
from custos.deployment_binding import BindingError, establish as establish_startup_binding

VERSION = "1.4.0"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger("main")

# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
policy_store = PolicyStore()
tenant_manager = TenantManager(policy_store=policy_store)
action_gate = ActionGate(tenant_manager)
validator = InputValidator()

# ---------------------------------------------------------------------------
# Chain-head custody (docs/design/chain-head-custody.md) — additive,
# disabled by default (CUSTOS_CUSTODY_ENABLED). Fail-visible: a sink
# outage never blocks enforcement; gaps are recorded and surfaced.
# ---------------------------------------------------------------------------

def _tenant_chains() -> dict:
    out = {}
    for tenant_id in tenant_manager.list_tenants():
        ctx = tenant_manager.get(tenant_id)
        if ctx is not None:
            out[tenant_id] = ctx.audit_chain
    return out


custody_manager: AnchorManager | None = build_custody_from_env(_tenant_chains)
# Policy-commit citation anchoring (docs/design/policy-commit-citation.md):
# the gate stamps every record with the in-force policy digest; when custody
# is enabled it also anchors each new policy commit to the same sinks.
if custody_manager is not None:
    action_gate.set_custody(custody_manager)
policy_differ = PolicyDiffer()

# Execution adapter — configurable target allowlist via CUSTOS_TARGET_ALLOWLIST
# (comma-separated hostnames). Empty = allow any HTTPS host.
_target_allowlist_str = os.getenv("CUSTOS_TARGET_ALLOWLIST", "")
_target_allowlist = set(
    h.strip() for h in _target_allowlist_str.split(",") if h.strip()
) if _target_allowlist_str else None
execution_adapter = HTTPExecutionAdapter(
    allowlist=_target_allowlist,
    timeout=float(os.getenv("CUSTOS_EXECUTION_TIMEOUT", "10.0")),
    circuit_threshold=int(os.getenv("CUSTOS_CIRCUIT_THRESHOLD", "5")),
    circuit_reset=float(os.getenv("CUSTOS_CIRCUIT_RESET", "30.0")),
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
    # Refusals that happen before a decision is reached. Issue 158: total minus
    # the outcome counters used to be one remainder that mixed a 422, a 403 and a
    # 429, so an operator could not tell a throttle from a bad request from a
    # tenancy error. Each site now labels its own refusal, and the labels are
    # required to sum to the remainder by tests/test_slo_accounting.py.
    "custos_refused_invalid_request": 0,
    "custos_refused_unknown_tenant": 0,
    "custos_refused_rate_limited": 0,
    # Decisions whose record could not be persisted. A subset of the decided
    # counters, not a refusal before a decision: the policy was consulted and the
    # caller got a 503, so the decision happened and the audit chain does not have
    # it. That is an audit burn, counted where SLO-3 can see it.
    "custos_decisions_unrecorded": 0,
    "custos_executions_forwarded": 0,
    "custos_executions_blocked": 0,
    "custos_circuit_open": 0,
    "custos_uptime_start": time.time(),
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False)


async def optional_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[str]:
    if not auth_enabled():
        return None
    return verify_token(credentials)


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[str]:
    """Strict auth for administrative endpoints (audit, replay, tenants, policy).

    Fail-closed: when auth is enabled, a valid bearer token is REQUIRED
    to read audit logs, verify snapshots, replay decisions, or manage
    tenants and policies. AUTH_DISABLED=1 (non-production only) disables
    for dev/test convenience; production forces auth (see auth_enabled()).
    """
    if not auth_enabled():
        return None
    return verify_token(credentials)


# ---------------------------------------------------------------------------
# Admin router — every route mounted here requires authentication when auth
# is enabled. New administrative endpoints must be added to admin_router
# (never bare @app), so they inherit this dependency automatically.
# ---------------------------------------------------------------------------
admin_router = APIRouter(dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
_startup_binding: Optional[dict] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_binding
    # Fail-closed security validation: refuse to start in production with
    # missing/dev-default secrets (strict env-presence rule) or, in RS256
    # mode, a missing explicit private key.
    validate_production_secrets()
    validate_production_key()
    # Refuse a topology the process cannot back: rate-limit counters and the
    # audit chain are process-local by default, so more than one replica means
    # quotas multiply by the replica count and each process carries its own
    # chain. The check validates the operator's declaration against the storage
    # actually configured, and cannot detect how many processes are really up.
    _default_ctx = tenant_manager.get("default")
    _audit_backend = (
        _default_ctx.audit_chain.backend_type if _default_ctx is not None else "memory"
    )
    _replica_summary = validate_replica_configuration(_audit_backend)
    logger.info("custos.topology", extra=_replica_summary)
    # Refuse a production process whose audit store cannot outlive it. The
    # wiring means the environment now selects a durable backend; this is the
    # half that refuses to run without one, so the guard and the mechanism
    # arrive together rather than one of them waiting for the other.
    try:
        _persistence_summary = require_durable_audit(_audit_backend)
    except AuditPersistenceRefused as exc:
        logger.error("custos.audit_persistence.refused", extra={"reason": str(exc)})
        raise
    logger.info("custos.audit_persistence", extra=_persistence_summary)
    # Whether the served path keeps the content it reads, and therefore whether
    # an erasure request has anything to act on. Validated at startup because
    # both mistakes it catches (a store configured but unused, a retention mode
    # with nowhere to store) are invisible at request time.
    try:
        _retention_summary = validate_content_retention()
    except RetentionConfigRefused as exc:
        logger.error("custos.content_retention.refused", extra={"reason": str(exc)})
        raise
    logger.info("custos.content_retention", extra=_retention_summary)
    if _retention_summary["content_retention"] == MODE_OFF:
        logger.warning(
            "custos.content_retention.off",
            extra={
                "consequence": (
                    "the served path keeps no content, so an erasure request "
                    "against it has nothing to act on and is refused"
                )
            },
        )
    if custody_manager is not None:
        custody_manager.start()
        logger.info("custos.custody.enabled")
    # Deployment binding: opt-in via CUSTOS_DEPLOYMENT_BINDING, and fail-closed
    # when opted into. A deployment that asks to be bound and cannot write its
    # record is refused rather than started unbound, because an unbound process
    # would still be described by an inventory that says the mechanism is wired.
    try:
        _startup_binding = establish_startup_binding(
            tenant_manager.get("default").audit_chain,
            policy_digest=action_gate.cited_policy_digest("default"),
        )
    except BindingError as exc:
        # Refuse to start. A process that was asked to be bound and could not
        # record it must not run while the inventory describes the mechanism
        # as wired: that is the exact confusion the binding exists to prevent.
        logger.error("custos.deployment_binding.refused", extra={"reason": str(exc)})
        raise
    if _startup_binding is not None:
        logger.info(
            "custos.deployment_binding.established",
            extra={
                "deployment_id": _startup_binding["deployment_id"],
                "binding_digest": _startup_binding["binding_digest"],
            },
        )
    logger.info("custos.startup", extra={"version": VERSION})
    yield
    if custody_manager is not None:
        custody_manager.stop()
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

# ---------------------------------------------------------------------------
# JWKS discovery — public by design (RFC 7517). Lets clients and external
# verifiers confirm RS256 token signatures without sharing any secret.
# ---------------------------------------------------------------------------
@app.get("/.well-known/jwks.json", tags=["auth"])
async def well_known_jwks() -> dict:
    return get_jwks_document()


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        uptime_seconds=round(time.time() - _metrics["custos_uptime_start"], 1),
    )


def custody_check_status() -> str:
    """Custody state for /ready: ok / disabled / pending / stale / fail.

    Fail-visible reporting only — a stale or failed sink surfaces here but
    never flips overall readiness (enforcement is never blocked on custody).
    """
    if custody_manager is None:
        return "disabled"
    h = custody_manager.health()
    if not h["sinks_healthy"]:
        return "fail"
    if not h["tenants"]:
        return "pending"
    if any(t.get("stale") or t.get("pending_gap") for t in h["tenants"].values()):
        return "stale"
    return "ok"


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
    checks_out = {k: "ok" if v else "fail" for k, v in checks.items()}
    # Chain-head custody: fail-visible surface. Reports state; per the
    # design (fail-visible, not fail-blocking) it never gates readiness.
    checks_out["custody"] = custody_check_status()
    return ReadyResponse(
        status="ready" if all_ready else "not_ready",
        checks=checks_out,
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
        "# HELP custos_refused_total Requests refused before a decision was reached",
        "# TYPE custos_refused_total counter",
        f'custos_refused_total{{kind="invalid_request"}} {_metrics["custos_refused_invalid_request"]}',
        f'custos_refused_total{{kind="unknown_tenant"}} {_metrics["custos_refused_unknown_tenant"]}',
        f'custos_refused_total{{kind="rate_limited"}} {_metrics["custos_refused_rate_limited"]}',
        "# HELP custos_decisions_unrecorded Decisions whose record could not be persisted",
        "# TYPE custos_decisions_unrecorded counter",
        f"custos_decisions_unrecorded {_metrics['custos_decisions_unrecorded']}",
        "# HELP custos_audit_chain_length Total audit records (default tenant)",
        "# TYPE custos_audit_chain_length gauge",
        f"custos_audit_chain_length {audit_length}",
        "# HELP custos_tenant_count Registered tenants",
        "# TYPE custos_tenant_count gauge",
        f"custos_tenant_count {tenant_manager.count}",
        "# HELP custos_uptime_seconds Seconds since startup",
        "# TYPE custos_uptime_seconds gauge",
        f"custos_uptime_seconds {uptime}",
        "# HELP custos_custody_enabled Chain-head custody enabled",
        "# TYPE custos_custody_enabled gauge",
        f"custos_custody_enabled {1 if custody_manager is not None else 0}",
    ]
    if custody_manager is not None:
        h = custody_manager.health()
        ages = [
            t["anchor_age_seconds"]
            for t in h["tenants"].values()
            if t["anchor_age_seconds"] is not None
        ]
        lines += [
            "# HELP custos_custody_sink_health All custody sinks healthy",
            "# TYPE custos_custody_sink_health gauge",
            f"custos_custody_sink_health {1 if h['sinks_healthy'] else 0}",
            "# HELP custos_custody_anchor_age_seconds Age of newest anchor",
            "# TYPE custos_custody_anchor_age_seconds gauge",
            f"custos_custody_anchor_age_seconds {max(ages) if ages else -1}",
        ]
    return "\n".join(lines) + "\n"


def _startup_binding_or_disabled() -> dict:
    """Report the binding state of THIS process, not of the mechanism."""
    if _startup_binding is None:
        return {"enabled": False, "established": False}
    summary = {k: v for k, v in _startup_binding.items() if k != "payload"}
    return {**summary, "established": True}


# How long a caller is told to wait when the store is full. A hint, not a promise:
# space returning is an operator action, and the drill measured resume only after
# the store could accept writes again.
AUDIT_STORE_FULL_RETRY_AFTER = 30


@app.exception_handler(AuditStoreFull)
async def audit_store_full_handler(request: Request, exc: AuditStoreFull):
    """A full audit store is a refusal with a reason, not a 500.

    Status 503 because the service cannot serve this request now and can later:
    the item 1 drill showed it resumes from the last durable head when space
    returns. ``Retry-After`` carries the operator's recovery window as a hint
    rather than a promise, and ``X-CUSTOS-Refusal`` names the condition so a
    caller can branch on it without parsing prose.
    """
    logger.warning(
        "custos.audit.store_full",
        extra={"path": request.url.path, "reason": str(exc)},
    )
    # Counted here rather than at the raise site so it captures every path that
    # reaches the handler. This is deliberately NOT one of the refusal labels:
    # a decision was reached and a 503 was served, so it belongs in the decided
    # population, and the missing record is an audit burn for SLO-3.
    _metrics["custos_decisions_unrecorded"] += 1
    return JSONResponse(
        status_code=503,
        headers={
            "Retry-After": str(AUDIT_STORE_FULL_RETRY_AFTER),
            "X-CUSTOS-Refusal": "audit-store-full",
        },
        content={
            "detail": (
                "the audit store is full, so this decision was not recorded and "
                "the chain was not advanced. Retrying will not succeed until the "
                "store has space; nothing was served unrecorded"
            ),
            "reason": "audit_store_full",
            "retry_after_seconds": AUDIT_STORE_FULL_RETRY_AFTER,
        },
    )


@app.get("/v1/info")
async def info():
    """Version and backend information."""
    default_ctx = tenant_manager.get("default")
    return {
        "version": VERSION,
        "audit_backend": default_ctx.audit_chain.backend_type,
        "audit_durable": is_durable(default_ctx.audit_chain.backend_type),
        # Named, not inferred, and on the API surface rather than only in the
        # startup log: a reader who can reach this endpoint should not have to
        # guess which variable put the store in force.
        "audit_store_source": audit_store_source(),
        # Named on the surface, because "does this service keep what it reads"
        # is the first question an erasure claim has to answer and the worst one
        # to answer by inference from an environment variable.
        "content_retention": content_retention_mode(),
        "policy_backend": tenant_manager.policy_backend,
        "tenant_count": tenant_manager.count,
        "uptime_seconds": round(
            time.time() - _metrics["custos_uptime_start"], 1
        ),
        "deployment_binding": _startup_binding_or_disabled(),
    }


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

@app.post("/v1/evaluate_action", response_model=EvaluateResponse)
async def evaluate_action(
    req: EvaluateActionRequest,
    _auth: Optional[str] = Depends(optional_auth),
):
    """Pre-flight action gate: evaluate a PROPOSED agent action BEFORE execution.

    Deny-by-default: tools must be explicitly allowlisted per tenant
    (ActionGate.register_tools()); an unconfigured gate denies all actions.
    Fail-closed on unknown tenants. Every decision is audit-chained.
    """
    if _auth is not None and _auth != req.client_id:
        raise HTTPException(
            status_code=403,
            detail="Client identity does not match request client_id",
        )
    span = tracer.start_span("custos.evaluate_action")
    span.set_attribute("client_id", req.client_id)
    span.set_attribute("tenant_id", req.tenant_id)
    span.set_attribute("tool", req.tool)

    gate_result = action_gate.evaluate_action(
        tenant_id=req.tenant_id,
        action=ActionRequest(tool=req.tool, command=req.command, args=req.args),
        client_id=req.client_id,
    )
    decision = gate_result.decision

    if decision.allowed:
        _metrics["custos_requests_allowed"] += 1
    else:
        _metrics["custos_requests_denied"] += 1

    tracer.finish_span(span)
    return EvaluateResponse(
        allowed=decision.allowed,
        action=decision.action.value,
        triggered_rule=decision.triggered_rule,
        reason=decision.reason,
        client_id=req.client_id,
        tenant_id=req.tenant_id,
        audit_record_hash=gate_result.audit_record_hash,
        trace_id=span.trace_id,
    )


# ---------------------------------------------------------------------------
# Recording a decision, with or without the content it decided on
# ---------------------------------------------------------------------------

def _record_decision(
    ctx,
    *,
    content: str,
    client_id: str,
    action: str,
    reason: str,
    triggered_rule=None,
    trace_id=None,
    policy_digest=None,
):
    """Record a decision through the one shared retention-aware path.

    The body of this used to live here. It moved to ``custos.retention`` when the
    action gate needed the same ordering, because two copies of store-then-record
    is how one of them ends up recording a form the store did not use. This wrapper
    stays so the call sites and their tests read the same as before.
    """
    return record_decision(
        ctx,
        content=content,
        client_id=client_id,
        action=action,
        reason=reason,
        triggered_rule=triggered_rule,
        trace_id=trace_id,
        policy_digest=policy_digest,
    )


def _unretained_record(
    ctx,
    *,
    content: str,
    client_id: str,
    action: str,
    reason: str,
    triggered_rule=None,
    trace_id=None,
    policy_digest=None,
):
    """Record a decision without keeping its content.

    One place that says ``none`` out loud, so the three reasons for it (retention
    off, content purged earlier, a caller that is not the retention path) do not
    drift into three different spellings of the same statement.
    """
    return ctx.audit_chain.record(
        client_id=client_id,
        action=action,
        reason=reason,
        content=content,
        triggered_rule=triggered_rule,
        trace_id=trace_id,
        policy_digest=policy_digest,
        commitment=COMMITMENT_NONE,
    )



@app.post("/v1/evaluate", response_model=EvaluateResponse)
async def evaluate(
    req: EvaluateRequest,
    _auth: Optional[str] = Depends(optional_auth),
):
    if _auth is not None and _auth != req.client_id:
        raise HTTPException(
            status_code=403,
            detail="Client identity does not match request client_id",
        )
    span = tracer.start_span("custos.evaluate")
    span.set_attribute("client_id", req.client_id)
    span.set_attribute("tenant_id", req.tenant_id)
    _metrics["custos_requests_total"] += 1

    val = validator.validate_request(req.client_id, req.content, req.token_count)
    if not val.valid:
        span.set_status("ERROR")
        tracer.finish_span(span)
        _metrics["custos_refused_invalid_request"] += 1
        raise HTTPException(status_code=422, detail=val.error)

    ctx = tenant_manager.get_strict(req.tenant_id)
    if ctx is None:
        _metrics["custos_refused_unknown_tenant"] += 1
        raise HTTPException(status_code=403, detail=f"Unknown tenant: {req.tenant_id}")
    rate_key = (
        f"{req.tenant_id}:{req.client_id}"
        if req.tenant_id != "default"
        else req.client_id
    )

    if ctx.rate_limiter.get_all_quotas().get(rate_key) is None:
        # New per-client key: inherit the TENANT'S configured quota (the
        # quota registered at tenant creation under the tenant-level key),
        # falling back to the conservative default only if it is absent.
        # A hardcoded 60/min here would silently ignore the tenant API's
        # requests_per_minute contract (observed by the benchmark suite).
        tenant_quota = ctx.rate_limiter.get_quota(ctx.tenant_id)
        ctx.rate_limiter.register(
            rate_key,
            tenant_quota or QuotaConfig(requests_per_minute=60, requests_per_hour=1000),
        )

    allowed, msg = ctx.rate_limiter.check_and_consume(rate_key, req.token_count)
    if not allowed:
        _metrics["custos_rate_limit_hits"] += 1
        _metrics["custos_refused_rate_limited"] += 1
        # The refusal is a decision and has to be recorded like one. It was
        # written without a policy citation, which production refuses: every
        # request past a client's quota raised ValueError inside the refusal
        # and returned 500 instead of 429, so the caller was never told to wait
        # and Retry-After never reached them. Found by the restore drill's
        # write loop, which stopped at exactly the quota and only then.
        _record_decision(
            ctx,
            content=req.content,
            client_id=req.client_id,
            action="rate_limited",
            reason=msg,
            trace_id=span.trace_id,
            policy_digest=content_engine_digest(ctx.policy_engine),
        )
        span.set_status("RATE_LIMITED")
        tracer.finish_span(span)
        wait = ctx.rate_limiter.retry_after_seconds(rate_key, req.token_count)
        raise HTTPException(
            status_code=429,
            detail=msg,
            headers={"Retry-After": str(wait)} if wait is not None else None,
        )

    result: PolicyResult = ctx.policy_engine.evaluate(req.content)

    if result.allowed:
        if result.action.value == "audit":
            _metrics["custos_requests_audited"] += 1
        else:
            _metrics["custos_requests_allowed"] += 1
    else:
        _metrics["custos_requests_denied"] += 1

    # Cite the policy the decision actually consulted. Production requires a
    # bound record (bound_evidence_required), and this endpoint passed a
    # trace_id but never a digest, so in production every request to it failed
    # with "the preimage would carry an unbound record" and returned 500. The
    # digest comes from the content engine's rule set, which is what decided
    # here -- not the gate's tool allowlist, which this endpoint never reads.
    audit_entry = _record_decision(
        ctx,
        content=req.content,
        client_id=req.client_id,
        action=result.action.value,
        reason=result.reason,
        triggered_rule=result.triggered_rule,
        trace_id=span.trace_id,
        policy_digest=content_engine_digest(ctx.policy_engine),
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

@admin_router.get("/v1/audit", response_model=list[AuditRecordResponse])
async def get_audit_log(
    client_id: Optional[str] = None,
    tenant_id: str = "default",
):
    ctx = tenant_manager.get_strict(tenant_id)
    if ctx is None:
        raise HTTPException(status_code=403, detail=f"Unknown tenant: {tenant_id}")
    return ctx.audit_chain.get_records(client_id=client_id)


@admin_router.get("/v1/audit/verify")
async def verify_audit_chain(
    tenant_id: str = "default",
):
    ctx = tenant_manager.get_strict(tenant_id)
    if ctx is None:
        raise HTTPException(status_code=403, detail=f"Unknown tenant: {tenant_id}")
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

@admin_router.get("/v1/audit/snapshot", response_model=SnapshotResponse)
async def get_snapshot(
    tenant_id: str = "default",
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
):
    ctx = tenant_manager.get_strict(tenant_id)
    if ctx is None:
        raise HTTPException(status_code=403, detail=f"Unknown tenant: {tenant_id}")
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


@admin_router.post("/v1/audit/snapshot/verify", response_model=SnapshotVerifyResponse)
async def verify_snapshot(
    req: SnapshotVerifyRequest,
):
    ctx = tenant_manager.get("default")
    engine = SnapshotEngine(ctx.audit_chain)
    valid, reason = engine.verify_snapshot(req.snapshot)
    return SnapshotVerifyResponse(valid=valid, reason=reason)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Retention: status and erasure
# ---------------------------------------------------------------------------

def require_retention_admin(
    x_custos_retention_token: Optional[str] = Header(
        default=None, alias="X-CUSTOS-Retention-Token"
    ),
) -> None:
    """Operator credential for the retention surface.

    Three refusals, each with its own reason, because they are different
    situations for whoever is holding the header:

    - retention is off: there is nothing stored, so a deletion call is not
      refused for lack of authority but because it would delete nothing;
    - no token configured: the administration surface does not exist, rather
      than accepting anyone who finds it;
    - token wrong or absent: authorized callers only.
    """
    if content_retention_mode() == MODE_OFF:
        raise HTTPException(
            status_code=503,
            detail=(
                f"content retention is off ({MODE_ENV}={MODE_OFF}); the served "
                "path keeps no content, so an erasure request has nothing to act "
                "on. This is a refusal, not a completed deletion"
            ),
        )
    token = admin_token()
    if token is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"retention administration is not configured; set {ADMIN_TOKEN_ENV}. "
                "Content is being withheld from erasure until an operator "
                "credential exists, and this endpoint stays closed rather than open"
            ),
        )
    if x_custos_retention_token is None or not hmac.compare_digest(
        x_custos_retention_token, token
    ):
        raise HTTPException(status_code=401, detail="retention admin token missing or wrong")


@admin_router.get("/v1/retention/status", response_model=RetentionStatusResponse)
async def retention_status(
    tenant_id: str = "default",
    _admin: None = Depends(require_retention_admin),
):
    """Compare the record side against the store side for one tenant.

    This is the operational form of the check that closes the split-restore
    defect: a chain restored to before an erasure, beside a store that is past
    it, verifies green and its records claim content the store does not hold.
    Nothing reports that unless something is asked, so there is something to ask.
    """
    ctx = tenant_manager.get_strict(tenant_id)
    if ctx is None:
        raise HTTPException(status_code=403, detail=f"Unknown tenant: {tenant_id}")
    store = content_store_for(tenant_id)
    report = reconcile(ctx.audit_chain.get_records(), store)
    return RetentionStatusResponse(
        tenant_id=tenant_id,
        content_retention=content_retention_mode(),
        store_file=os.path.basename(store_path_for(store_directory(), tenant_id)),
        records_read=report.records_read,
        digests_examined=report.digests_examined,
        ok=report.ok,
        findings=[
            RetentionFinding(
                kind=f.kind,
                content_hash=f.content_hash,
                detail=f.detail,
                record_indexes=list(f.record_indexes),
            )
            for f in report.findings
        ],
    )


@admin_router.post("/v1/retention/purge", response_model=RetentionPurgeResponse)
async def retention_purge(
    req: RetentionPurgeRequest,
    _admin: None = Depends(require_retention_admin),
):
    """Delete a stored body, its salt and its commitment, and attest the deletion.

    The deletion happens before the attestation, and a failure to delete raises
    rather than returning a success: an attestation for content that is still
    readable is worse than a deletion with no record of it, because the record
    would be believed.
    """
    ctx = tenant_manager.get_strict(req.tenant_id)
    if ctx is None:
        raise HTTPException(status_code=403, detail=f"Unknown tenant: {req.tenant_id}")
    store = content_store_for(req.tenant_id)
    status = store.status(req.content_hash)
    if status == STATUS_UNKNOWN:
        raise HTTPException(
            status_code=409,
            detail=(
                f"the store holds no content at {req.content_hash[:16]}; a purge "
                "of something never stored would be recorded as a deletion that "
                "never happened"
            ),
        )
    if status == STATUS_PURGED:
        prior = store.purge_record(req.content_hash)
        raise HTTPException(
            status_code=409,
            detail=(
                f"content {req.content_hash[:16]} was already purged at "
                f"{prior['purged_at'] if prior else 'an earlier time'}"
            ),
        )
    try:
        attestation_hash = store.purge(
            req.content_hash,
            chain=ctx.audit_chain,
            client_id="retention-admin",
            reason=req.reason,
            policy_digest=content_engine_digest(ctx.policy_engine),
        )
    except (PurgeRefused, ContentPurged) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RetentionPurgeResponse(
        purged=True,
        content_hash=req.content_hash,
        attestation_hash=attestation_hash,
        store_status=store.status(req.content_hash),
        tenant_id=req.tenant_id,
    )


@admin_router.post("/v1/replay", response_model=ReplayResponse)
async def replay(
    req: ReplayRequest,
):
    ctx = tenant_manager.get_strict(req.tenant_id)
    if ctx is None:
        raise HTTPException(status_code=403, detail=f"Unknown tenant: {req.tenant_id}")
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

@admin_router.post("/v1/policy/diff", response_model=PolicyDiffResponse)
async def policy_diff(
    req: PolicyDiffRequest,
):
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
# Tenant Policy Rules (v1.1 -- persists across restarts, closes #20)
# ---------------------------------------------------------------------------

_ACTION_MAP = {
    "allow": PolicyAction.ALLOW,
    "deny": PolicyAction.DENY,
    "audit": PolicyAction.AUDIT,
}


@admin_router.post("/v1/tenants/{tenant_id}/policy", response_model=PolicyRuleAddResponse)
async def add_tenant_policy_rule(
    tenant_id: str,
    req: PolicyRuleRequest,
):
    """
    Add a custom policy rule for a tenant. The rule is applied immediately
    and persisted via PolicyStore, so it survives pod restarts, rollouts,
    and autoscaling events when a durable backend (POLICY_DB_PATH or
    DATABASE_URL) is configured.
    """
    try:
        action = _ACTION_MAP[req.action]
    except KeyError:
        raise HTTPException(status_code=422, detail=f"Invalid action: {req.action}")

    rule = PolicyRule(
        name=req.name, pattern=req.pattern, action=action, reason=req.reason
    )
    tenant_manager.add_policy_rule(tenant_id, rule)
    total = len(tenant_manager.list_policy_rules(tenant_id))

    logger.info("policy.rule_added", extra={
        "tenant_id": tenant_id, "rule_name": req.name,
    })

    return PolicyRuleAddResponse(
        tenant_id=tenant_id, rule=req, total_custom_rules=total
    )


@admin_router.get("/v1/tenants/{tenant_id}/policy", response_model=PolicyRuleListResponse)
async def list_tenant_policy_rules(
    tenant_id: str,
):
    """List custom (persisted) policy rules for a tenant. Excludes defaults."""
    rules = tenant_manager.list_policy_rules(tenant_id)
    rule_requests = [
        PolicyRuleRequest(
            name=r.name, pattern=r.pattern, action=r.action.value, reason=r.reason
        )
        for r in rules
    ]
    return PolicyRuleListResponse(
        tenant_id=tenant_id, rules=rule_requests, count=len(rule_requests)
    )


# ---------------------------------------------------------------------------
# Tenant Management
# ---------------------------------------------------------------------------

@admin_router.post("/v1/tenants", response_model=TenantResponse)
async def register_tenant(
    req: TenantRegisterRequest,
):
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


@admin_router.get("/v1/tenants", response_model=TenantListResponse)
async def list_tenants(
):
    tenants = tenant_manager.list_tenants()
    return TenantListResponse(tenants=tenants, count=len(tenants))


@admin_router.delete("/v1/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
):
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


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Enterprise Routes — /v1/execute (conditionally loaded)
# ---------------------------------------------------------------------------
# The /v1/execute endpoints are enterprise features assembled by the
# custos-enterprise package. When the enterprise router module is
# installed, /v1/execute is available. When absent (public-only
# deployment), the endpoints are simply not registered — no stubs,
# no degraded behavior, no accidental exposure.

try:
    from custos_enterprise.enterprise_router import mount_enterprise_routes
    mount_enterprise_routes(
        app=app,
        tenant_manager=tenant_manager,
        validator=validator,
        tracer=tracer,
        execution_adapter=execution_adapter,
        metrics=_metrics,
        version=VERSION,
        optional_auth=optional_auth,
    )
    logger.info("enterprise.routes.mounted", extra={"endpoints": ["/v1/execute", "/v1/execute/circuit", "/v1/execute/circuit/reset"]})
except ImportError:
    logger.info("enterprise.routes.not_available", extra={"reason": "custos-enterprise not installed — public-only deployment"})

# Mount the admin router (must come after all its routes are defined).
app.include_router(admin_router)
