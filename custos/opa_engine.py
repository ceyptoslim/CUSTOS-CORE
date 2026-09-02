"""
CUSTOS OPA Policy Engine — Open Policy Agent integration.

When CUSTOS_POLICY_ENGINE=opa, this engine queries an OPA server
instead of using the regex-based engine.

Fail mode: CLOSED. If OPA is unavailable, returns DENY.
This is the enforcement layer — restrictive by design.

Requires: pip install httpx
Requires: OPA server running at CUSTOS_OPA_URL (default: http://localhost:8181)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from custos.policy_engine import PolicyAction, PolicyResult

logger = logging.getLogger(__name__)


class OPAPolicyEngine:
    """OPA-backed policy engine. Queries OPA /v1/data/custos/governance/allow."""

    def __init__(self, opa_url: str | None = None) -> None:
        self.opa_url = (opa_url or os.getenv("CUSTOS_OPA_URL", "http://localhost:8181")).rstrip("/")

    def evaluate(self, content: str) -> PolicyResult:
        """Query OPA for policy decision. Fails CLOSED if OPA is unavailable."""
        input_data: dict[str, Any] = {
            "content": content,
            "action_type": "custos_evaluate",
        }
        url = f"{self.opa_url}/v1/data/custos/governance/allow"

        try:
            # httpx sync client — CUSTOS evaluate is synchronous
            with httpx.Client() as client:
                response = client.post(url, json={"input": input_data}, timeout=5.0)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, Exception) as exc:
            logger.error("OPA policy server unavailable at %s (failing CLOSED): %s", url, exc)
            return PolicyResult(
                allowed=False,
                action=PolicyAction.DENY,
                triggered_rule="opa_unavailable",
                reason=f"OPA policy server unavailable — failing closed: {exc}",
            )

        result = data.get("result")

        if isinstance(result, dict):
            allowed = bool(result.get("allow", False))
            deny_reasons = list(result.get("deny") or result.get("deny_messages") or [])
            triggered = result.get("triggered_rule")
        elif isinstance(result, bool):
            allowed = result
            deny_reasons = list(data.get("deny") or [])
            triggered = data.get("triggered_rule")
        else:
            allowed = False
            deny_reasons = ["OPA returned unexpected response format"]
            triggered = "opa_parse_error"

        audit_flag = result.get("audit") if isinstance(result, dict) else None

        if not allowed and audit_flag is True:
            return PolicyResult(
                allowed=True,
                action=PolicyAction.AUDIT,
                triggered_rule=triggered or "opa_audit",
                reason="; ".join(deny_reasons) if deny_reasons else "Flagged for audit by OPA",
            )

        if not allowed:
            reason = "; ".join(deny_reasons) if deny_reasons else "Denied by OPA policy"
            return PolicyResult(
                allowed=False,
                action=PolicyAction.DENY,
                triggered_rule=triggered or "opa_deny",
                reason=reason,
            )

        if allowed and audit_flag is True:
            return PolicyResult(
                allowed=True,
                action=PolicyAction.AUDIT,
                triggered_rule=triggered or "opa_audit",
                reason="; ".join(deny_reasons) if deny_reasons else "Flagged for audit by OPA",
            )

        return PolicyResult(
            allowed=True,
            action=PolicyAction.ALLOW,
            triggered_rule=triggered,
            reason="Allowed by OPA policy",
        )

    @property
    def rule_count(self) -> int:
        """OPA rules are dynamic — return 0 as a sentinel."""
        return 0

    def add_rule(self, rule: Any) -> None:
        """OPA rules are managed in Rego files, not added at runtime."""
        logger.warning("OPA rules are managed via Rego policy files, not runtime add_rule()")

    def evaluate_with_metadata(self, content: str, client_id: str = "", action_type: str = "custos_evaluate") -> PolicyResult:
        """Extended evaluate with client_id and action_type for tenant-specific OPA policies."""
        input_data: dict[str, Any] = {
            "content": content,
            "client_id": client_id,
            "action_type": action_type,
        }
        url = f"{self.opa_url}/v1/data/custos/governance/allow"

        try:
            with httpx.Client() as client:
                response = client.post(url, json={"input": input_data}, timeout=5.0)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, Exception) as exc:
            logger.error("OPA policy server unavailable at %s (failing CLOSED): %s", url, exc)
            return PolicyResult(
                allowed=False,
                action=PolicyAction.DENY,
                triggered_rule="opa_unavailable",
                reason=f"OPA policy server unavailable — failing closed: {exc}",
            )

        result = data.get("result")

        if isinstance(result, dict):
            allowed = bool(result.get("allow", False))
            deny_reasons = list(result.get("deny") or result.get("deny_messages") or [])
            triggered = result.get("triggered_rule")
            audit_flag = result.get("audit")
        elif isinstance(result, bool):
            allowed = result
            deny_reasons = list(data.get("deny") or [])
            triggered = data.get("triggered_rule")
            audit_flag = None
        else:
            allowed = False
            deny_reasons = ["OPA returned unexpected response format"]
            triggered = "opa_parse_error"
            audit_flag = None

        if not allowed and audit_flag is True:
            return PolicyResult(
                allowed=True,
                action=PolicyAction.AUDIT,
                triggered_rule=triggered or "opa_audit",
                reason="; ".join(deny_reasons) if deny_reasons else "Flagged for audit by OPA",
            )

        if not allowed:
            reason = "; ".join(deny_reasons) if deny_reasons else "Denied by OPA policy"
            return PolicyResult(
                allowed=False,
                action=PolicyAction.DENY,
                triggered_rule=triggered or "opa_deny",
                reason=reason,
            )

        return PolicyResult(
            allowed=True,
            action=PolicyAction.ALLOW,
            triggered_rule=triggered,
            reason="Allowed by OPA policy",
        )
