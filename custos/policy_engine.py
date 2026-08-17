"""
CUSTOS Policy Engine
Hardened regex-based pattern matching with Luhn validation for credit cards.
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


def _luhn_valid(card_digits: str) -> bool:
    """Luhn checksum validation. Returns True if digits pass the Luhn algorithm."""
    digits = [int(d) for d in card_digits if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# ---------------------------------------------------------------------------
# Hardened default rules
# ---------------------------------------------------------------------------

DEFAULT_RULES: List[PolicyRule] = [
    # --- PII: SSN ---
    # Catches dashed (123-45-6789), spaced (123 45 6789), and dotted (123.45.6789) formats.
    # Area number validation: rejects 000, 666, and 900-999 ranges (invalid SSN areas).
    PolicyRule(
        name="block_pii_ssn",
        pattern=(
            r"\b(?!000|666|9\d{2})"
            r"\d{3}[- .]\d{2}[- .]\d{4}\b"
        ),
        action=PolicyAction.DENY,
        reason="SSN pattern detected",
    ),
    # Also catch unformatted SSN (123456789) when preceded by SSN-like context
    PolicyRule(
        name="block_pii_ssn_compact",
        pattern=r"(?i)\b(?:ssn|social\s+security)\s*(?:#|no\.?|number)?\s*:?\s*\d{9}\b",
        action=PolicyAction.DENY,
        reason="SSN pattern detected (compact format)",
    ),
    # --- PII: Credit Card ---
    # Catches 13-19 digit cards with spaces, dashes, or no separators.
    # Luhn validation is applied post-match in the engine to reduce false positives.
    PolicyRule(
        name="block_pii_credit_card",
        pattern=r"\b(?:\d[ \-.\n]*?){13,19}\b",
        action=PolicyAction.DENY,
        reason="Credit card pattern detected",
    ),
    # --- Prompt Injection ---
    # Expanded set covering common injection vectors.
    PolicyRule(
        name="block_prompt_injection",
        pattern=(
            r"(?i)("
            r"ignore\s+(?:previous|prior|all|the\s+above)\s+instructions?"
            r"|disregard\s+(?:your|the|all|previous)\s+(?:instructions?|rules?|guidelines?)"
            r"|forget\s+(?:your|all|previous)\s+(?:instructions?|rules?|prompt)"
            r"|override\s+(?:your|the|system)\s+(?:system\s+)?(?:instructions?|prompt|rules?)"
            r"|you\s+are\s+now\s+(?:a|an|in)"
            r"|act\s+as\s+(?:if\s+you\s+are|a|an)"
            r"|pretend\s+(?:you\s+are|to\s+be)"
            r"|jailbreak|dan\s+mode|developer\s+mode"
            r"|system\s*:\s*(?:new|override|ignore)"
            r"|new\s+instructions?\s*:"
            r"|stop\s+following\s+(?:your|the|all)\s+rules?"
            r"|reveal\s+(?:your|the|all)\s+(?:system\s+)?(?:prompt|instructions?|rules?)"
            r"|show\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?prompt"
            r")"
        ),
        action=PolicyAction.DENY,
        reason="Prompt injection attempt detected",
    ),
    # --- Sensitive keywords (audit only) ---
    PolicyRule(
        name="audit_sensitive_keywords",
        pattern=r"(?i)\b(password|passwd|secret|token|api[_\s-]?key|credentials?|private[_\s-]?key)\b",
        action=PolicyAction.AUDIT,
        reason="Sensitive keyword flagged for audit",
    ),
]


# Rules that require post-match validation (e.g., Luhn check for credit cards)
_POST_VALIDATION_RULES = {"block_pii_credit_card"}


class PolicyEngine:
    def __init__(self, rules: Optional[List[PolicyRule]] = None):
        self._rules = rules if rules is not None else list(DEFAULT_RULES)

    def evaluate(self, content: str) -> PolicyResult:
        """
        Evaluate content against all rules. DENY takes precedence over AUDIT.
        Returns first DENY hit, or first AUDIT hit, or ALLOW if no match.

        For rules requiring post-match validation (e.g., Luhn checksum for
        credit cards), the match is only counted as a hit if validation passes.
        """
        audit_hit: Optional[PolicyRule] = None

        for rule in self._rules:
            match = re.search(rule.pattern, content)
            if match:
                # Apply post-match validation if needed
                if rule.name in _POST_VALIDATION_RULES:
                    matched_text = match.group(0)
                    digits_only = re.sub(r"[^0-9]", "", matched_text)
                    if not _luhn_valid(digits_only):
                        continue  # False positive — skip this match

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
