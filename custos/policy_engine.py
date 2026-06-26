"""
CUSTOS Policy Engine
Prototype-grade: regex-based pattern matching. Sufficient for demo/MVP.
Production upgrade path: replace with OPA or structured DSL evaluation.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class PolicyAction(Enum):
    ALLOW = "allow"
    DENY = "deny"
    AUDIT = "audit"


@dataclass
class PolicyRule:
    name: str
    pattern: str
    action: PolicyAction
    reason: str


@dataclass
class PolicyResult:
    allowed: bool
    action: PolicyAction
    triggered_rule: Optional[str]
    reason: str


DEFAULT_RULES: List[PolicyRule] = [
    PolicyRule(
        name="block_pii_ssn",
        pattern=r"\b\d{3}-\d{2}-\d{4}\b",
        action=PolicyAction.DENY,
        reason="SSN pattern detected",
    ),
    PolicyRule(
        name="block_pii_credit_card",
        pattern=r"\b(?:\d{4}[- ]?){3}\d{4}\b",
        action=PolicyAction.DENY,
        reason="Credit card pattern detected",
    ),
    PolicyRule(
        name="block_prompt_injection",
        pattern=r"(?i)(ignore previous instructions|disregard your|you are now|jailbreak)",
        action=PolicyAction.DENY,
        reason="Prompt injection attempt detected",
    ),
    PolicyRule(
        name="audit_sensitive_keywords",
        pattern=r"(?i)\b(password|secret|token|api[_\s]?key)\b",
        action=PolicyAction.AUDIT,
        reason="Sensitive keyword flagged for audit",
    ),
]


class PolicyEngine:
    def __init__(self, rules: Optional[List[PolicyRule]] = None):
        self._rules = rules if rules is not None else list(DEFAULT_RULES)

    def evaluate(self, content: str) -> PolicyResult:
        """
        Evaluate content against all rules. DENY takes precedence over AUDIT.
        Returns first DENY hit, or first AUDIT hit, or ALLOW if no match.
        """
        audit_hit: Optional[PolicyRule] = None

        for rule in self._rules:
            if re.search(rule.pattern, content):
                if rule.action == PolicyAction.DENY:
                    return PolicyResult(
                        allowed=False,
                        action=PolicyAction.DENY,
                        triggered_rule=rule.name,
                        reason=rule.reason,
                    )
                elif rule.action == PolicyAction.AUDIT and audit_hit is None:
                    audit_hit = rule

        if audit_hit:
            return PolicyResult(
                allowed=True,
                action=PolicyAction.AUDIT,
                triggered_rule=audit_hit.name,
                reason=audit_hit.reason,
            )

        return PolicyResult(
            allowed=True,
            action=PolicyAction.ALLOW,
            triggered_rule=None,
            reason="No policy violations detected",
        )

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)

    @property
    def rule_count(self) -> int:
        return len(self._rules)
