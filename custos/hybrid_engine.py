"""
CUSTOS Hybrid Policy Engine — regex first, OPA second.

When CUSTOS_POLICY_ENGINE=hybrid, this engine:
1. Runs the regex-based engine (fast, local, always available)
2. If regex DENIES → return immediately (no need to query OPA)
3. If regex ALLOWS → query OPA for additional policy checks
4. If OPA is unavailable → return regex result (graceful fallback, NOT fail-closed)

This gives you the speed and reliability of regex for known patterns
(SSN, credit cards, prompt injection) PLUS the flexibility of OPA for
tenant-specific, complex, or business-logic policies.

Fail mode: GRACEFUL. Regex always runs. OPA failure falls back to regex result.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.



from __future__ import annotations

import logging
import os
from typing import Any

from custos.policy_engine import PolicyAction, PolicyResult, PolicyEngine as RegexEngine
from custos.opa_engine import OPAPolicyEngine

logger = logging.getLogger(__name__)


class HybridPolicyEngine:
    """Regex + OPA hybrid engine. Regex is the fast first-pass, OPA is the deep second-pass."""

    def __init__(
        self,
        regex_engine: RegexEngine | None = None,
        opa_engine: OPAPolicyEngine | None = None,
    ) -> None:
        self._regex = regex_engine or RegexEngine()
        self._opa = opa_engine or OPAPolicyEngine(
            opa_url=os.getenv("CUSTOS_OPA_URL", "http://localhost:8181")
        )

    def evaluate(self, content: str) -> PolicyResult:
        """
        Evaluate content through regex first, then OPA.

        Decision flow:
        1. Regex DENY → return immediately
        2. Regex AUDIT → check OPA, if OPA DENY return that, else return regex AUDIT
        3. Regex ALLOW → check OPA, return OPA result
        4. OPA unavailable → return regex result (graceful fallback)
        """
        # Phase 1: Regex (always runs, fast, local)
        regex_result = self._regex.evaluate(content)

        # If regex says DENY, no need to query OPA — it's already blocked
        if not regex_result.allowed:
            logger.debug("Regex engine DENIED: %s (skipping OPA)", regex_result.triggered_rule)
            return regex_result

        # Phase 2: OPA (only if regex allowed or audited)
        # Pass regex result metadata to OPA for richer policy decisions
        input_data: dict[str, Any] = {
            "content": content,
            "regex_result": {
                "allowed": regex_result.allowed,
                "action": regex_result.action.value,
                "triggered_rule": regex_result.triggered_rule,
                "reason": regex_result.reason,
            },
            "action_type": "custos_evaluate",
        }

        url = f"{self._opa.opa_url}/v1/data/custos/governance/allow"

        try:
            import httpx
            with httpx.Client() as client:
                response = client.post(url, json={"input": input_data}, timeout=5.0)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            # Graceful fallback: return regex result, don't block on OPA failure
            logger.warning("OPA unavailable in hybrid mode, falling back to regex result: %s", exc)
            return regex_result

        result = data.get("result")

        if isinstance(result, dict):
            opa_allowed = bool(result.get("allow", False))
            deny_reasons = list(result.get("deny") or result.get("deny_messages") or [])
            triggered = result.get("triggered_rule")
            audit_flag = result.get("audit")
        elif isinstance(result, bool):
            opa_allowed = result
            deny_reasons = list(data.get("deny") or [])
            triggered = data.get("triggered_rule")
            audit_flag = None
        else:
            # OPA returned unexpected format — fall back to regex
            logger.warning("OPA returned unexpected response format, falling back to regex")
            return regex_result

        # If regex AUDIT'd and OPA allows, keep the audit flag
        if regex_result.action == PolicyAction.AUDIT and opa_allowed:
            return regex_result  # Preserve audit annotation

        # If OPA wants to audit (not deny, but flag)
        if opa_allowed and audit_flag is True:
            return PolicyResult(
                allowed=True,
                action=PolicyAction.AUDIT,
                triggered_rule=triggered or "opa_audit",
                reason="; ".join(deny_reasons) if deny_reasons else "Flagged for audit by OPA",
            )

        # OPA DENY overrides regex ALLOW
        if not opa_allowed:
            reason = "; ".join(deny_reasons) if deny_reasons else "Denied by OPA policy"
            return PolicyResult(
                allowed=False,
                action=PolicyAction.DENY,
                triggered_rule=triggered or "opa_deny",
                reason=reason,
            )

        # Both allowed
        return PolicyResult(
            allowed=True,
            action=PolicyAction.ALLOW,
            triggered_rule=triggered or regex_result.triggered_rule,
            reason="Allowed by regex + OPA",
        )

    def evaluate_with_metadata(
        self, content: str, client_id: str = "", action_type: str = "custos_evaluate"
    ) -> PolicyResult:
        """Extended evaluate with tenant context for OPA tenant-specific policies."""
        regex_result = self._regex.evaluate(content)

        if not regex_result.allowed:
            return regex_result

        # Pass tenant context to OPA
        opa_result = self._opa.evaluate_with_metadata(content, client_id, action_type)

        if opa_result.triggered_rule == "opa_unavailable":
            # Graceful fallback
            return regex_result

        # If regex AUDIT'd and OPA allows, keep audit
        if regex_result.action == PolicyAction.AUDIT and opa_result.allowed:
            return regex_result

        return opa_result

    @property
    def rule_count(self) -> int:
        return self._regex.rule_count

    def add_rule(self, rule: Any) -> None:
        """Add rule to regex engine. OPA rules are managed via Rego files."""
        self._regex.add_rule(rule)
