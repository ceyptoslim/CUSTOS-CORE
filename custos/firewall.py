"""
CUSTOS Execution Firewall v1.2

The enforcement boundary. This is what makes CUSTOS a firewall, not
just a decision API.

Flow:
    Request → Validate → Rate Limit → Policy Evaluate → Execute or Block → Audit

The critical difference from /v1/evaluate:
- /v1/evaluate returns a decision as metadata. The caller may ignore it.
- /v1/execute (this module) physically blocks denied requests from
  reaching the downstream target. A DENY means the target is never contacted.

Fail-closed design:
- Any exception during validation, rate limiting, policy evaluation, or
  forwarding → request is blocked, never forwarded.
- The audit chain records what happened: allowed, denied, blocked,
  forwarded, failed, circuit_open.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

from custos.audit import AuditChain
from custos.execution import HTTPExecutionAdapter, ExecutionResult
from custos.policy_engine import PolicyEngine, PolicyResult
from custos.rate_limiter import RateLimiter
from custos.validation import InputValidator
from custos.tracing import Tracer

logger = logging.getLogger("custos.firewall")


@dataclass
class FirewallResult:
    """Complete result from the firewall pipeline."""
    allowed: bool
    action: str  # allow, deny, audit, rate_limited, blocked, forwarded, failed
    triggered_rule: Optional[str]
    reason: str
    forwarded: bool
    status_code: Optional[int]
    response_preview: Optional[str]
    circuit_open: bool
    audit_record_hash: Optional[str]
    trace_id: Optional[str]
    timing_ms: float


class ExecutionFirewall:
    """
    Orchestrates the full enforcement pipeline.

    This is the component that sits between the AI agent and the real world.
    It evaluates the request against policy, then either forwards it to
    the downstream target or blocks it.

    The caller never gets to bypass the policy decision.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        rate_limiter: RateLimiter,
        audit_chain: AuditChain,
        validator: InputValidator,
        execution_adapter: HTTPExecutionAdapter,
        tracer: Optional[Tracer] = None,
    ):
        self._engine = policy_engine
        self._limiter = rate_limiter
        self._audit = audit_chain
        self._validator = validator
        self._adapter = execution_adapter
        self._tracer = tracer

    def enforce(
        self,
        client_id: str,
        content: str,
        tenant_id: str = "default",
        token_count: int = 1,
        target_url: str = "",
        target_method: str = "POST",
        target_headers: Optional[dict[str, str]] = None,
        target_timeout: float = 10.0,
        rate_key: Optional[str] = None,
    ) -> FirewallResult:
        """
        Run the full enforcement pipeline.

        This is the ONLY method that should be called to execute a request
        through the firewall. It handles the complete flow:

        1. Validate input
        2. Check rate limits
        3. Evaluate policy
        4. If ALLOW → forward to target via execution adapter
        5. If DENY → block, never contact target
        6. Audit everything
        7. Return result

        Returns FirewallResult with forwarded=True if the request reached
        the target, forwarded=False if blocked.
        """
        start = time.time()
        span = self._tracer.start_span("custos.execute") if self._tracer else None
        trace_id = span.trace_id if span else None

        if span:
            span.set_attribute("client_id", client_id)
            span.set_attribute("tenant_id", tenant_id)
            span.set_attribute("target_url", target_url)

        # ── Step 1: Input Validation ──────────────────────────────────
        val = self._validator.validate_request(client_id, content, token_count)
        if not val.valid:
            if span:
                span.set_status("ERROR")
                self._tracer.finish_span(span)
            return FirewallResult(
                allowed=False, action="blocked",
                triggered_rule=None, reason=f"Validation failed: {val.error}",
                forwarded=False, status_code=None, response_preview=None,
                circuit_open=False, audit_record_hash=None,
                trace_id=trace_id, timing_ms=(time.time() - start) * 1000,
            )

        # ── Step 2: Rate Limiting ─────────────────────────────────────
        rk = rate_key or client_id
        allowed, msg = self._limiter.check_and_consume(rk, token_count)
        if not allowed:
            audit_entry = self._audit.record(
                client_id, "rate_limited", msg, content, trace_id=trace_id,
            )
            if span:
                span.set_status("RATE_LIMITED")
                self._tracer.finish_span(span)
            return FirewallResult(
                allowed=False, action="rate_limited",
                triggered_rule=None, reason=msg,
                forwarded=False, status_code=None, response_preview=None,
                circuit_open=False, audit_record_hash=audit_entry.record_hash,
                trace_id=trace_id, timing_ms=(time.time() - start) * 1000,
            )

        # ── Step 3: Policy Evaluation ────────────────────────────────
        result: PolicyResult = self._engine.evaluate(content)

        # ── Step 4: Enforcement Decision ──────────────────────────────
        if not result.allowed:
            # DENY → block, never contact target
            audit_entry = self._audit.record(
                client_id, result.action.value, result.reason, content,
                triggered_rule=result.triggered_rule, trace_id=trace_id,
            )
            if span:
                span.set_attribute("action", result.action.value)
                span.set_attribute("blocked", True)
                span.set_status("DENIED")
                self._tracer.finish_span(span)
            logger.info(
                "firewall.blocked",
                extra={
                    "client_id": client_id,
                    "tenant_id": tenant_id,
                    "action": result.action.value,
                    "rule": result.triggered_rule,
                    "trace_id": trace_id,
                },
            )
            return FirewallResult(
                allowed=False, action=result.action.value,
                triggered_rule=result.triggered_rule, reason=result.reason,
                forwarded=False, status_code=None, response_preview=None,
                circuit_open=False, audit_record_hash=audit_entry.record_hash,
                trace_id=trace_id, timing_ms=(time.time() - start) * 1000,
            )

        # ── Step 5: Forward to Target (ALLOW path) ───────────────────
        exec_result: ExecutionResult = self._adapter.forward(
            url=target_url,
            method=target_method,
            content=content,
            headers=target_headers,
            timeout=target_timeout,
        )

        # ── Step 6: Audit the Execution Outcome ──────────────────────
        if exec_result.forwarded:
            audit_action = "forwarded"
            audit_reason = f"Forwarded to {target_url} (HTTP {exec_result.status_code})"
        elif exec_result.circuit_open:
            audit_action = "circuit_open"
            audit_reason = "Circuit breaker open, request not forwarded"
        else:
            audit_action = "forward_failed"
            audit_reason = f"Forward failed: {exec_result.error}"

        audit_entry = self._audit.record(
            client_id, audit_action, audit_reason, content,
            triggered_rule=result.triggered_rule, trace_id=trace_id,
        )

        if span:
            span.set_attribute("action", "forwarded" if exec_result.forwarded else "blocked")
            span.set_attribute("forwarded", exec_result.forwarded)
            span.set_attribute("status_code", exec_result.status_code or 0)
            span.set_attribute("audit_record_hash", audit_entry.record_hash)
            span.set_status("OK" if exec_result.forwarded else "ERROR")
            self._tracer.finish_span(span)

        logger.info(
            "firewall.execute",
            extra={
                "client_id": client_id,
                "tenant_id": tenant_id,
                "action": audit_action,
                "forwarded": exec_result.forwarded,
                "status_code": exec_result.status_code,
                "trace_id": trace_id,
            },
        )

        # Use audit_action so the result reflects what actually happened
        final_action = audit_action if not exec_result.forwarded else result.action.value
        return FirewallResult(
            allowed=True,
            action=final_action,
            triggered_rule=result.triggered_rule,
            reason=audit_reason if not exec_result.forwarded else result.reason,
            forwarded=exec_result.forwarded,
            status_code=exec_result.status_code,
            response_preview=exec_result.response_body,
            circuit_open=exec_result.circuit_open,
            audit_record_hash=audit_entry.record_hash,
            trace_id=trace_id,
            timing_ms=(time.time() - start) * 1000,
        )
