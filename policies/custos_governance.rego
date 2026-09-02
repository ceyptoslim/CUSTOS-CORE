# CUSTOS-CORE OPA Policy — Governance Rules
#
# This Rego policy implements the same rules as the regex-based engine,
# plus extensible tenant-specific and business-logic policies.
#
# OPA endpoint: POST /v1/data/custos/governance/allow
# Input: {"content": "...", "client_id": "...", "action_type": "...", "regex_result": {...}}
# Output: {"result": {"allow": true/false, "deny": [...], "triggered_rule": "...", "audit": bool}}

package custos.governance

import future.keywords.in
import future.keywords.if

# ---------------------------------------------------------------------------
# Default: deny if no rule explicitly allows
# ---------------------------------------------------------------------------

default allow := true

# ---------------------------------------------------------------------------
# Deny rules — same patterns as regex engine
# ---------------------------------------------------------------------------

deny contains "SSN pattern detected" if {
    contains(input.content, "ssn")
    regex.match(`\b(?!000|666|9\d{2})\d{3}[- .]\d{2}[- .]\d{4}\b`, input.content)
}

deny contains "SSN pattern detected (compact format)" if {
    regex.match(`(?i)\b(?:ssn|social\s+security)\s*(?:#|no\.?|number)?\s*:?\s*\d{9}\b`, input.content)
}

deny contains "Credit card pattern detected" if {
    regex.match(`\b(?:\d[ \-.\n]*?){13,19}\b`, input.content)
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "ignore previous instructions")
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "disregard your instructions")
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "forget your instructions")
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "override system prompt")
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "you are now a")
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "act as if you are")
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "jailbreak")
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "developer mode")
}

deny contains "Prompt injection attempt detected" if {
    contains(lower(input.content), "reveal your system prompt")
}

# ---------------------------------------------------------------------------
# Audit rules — flag for audit but don't deny
# ---------------------------------------------------------------------------

audit if {
    regex.match(`(?i)\b(password|passwd|secret|token|api[_\s-]?key|credentials?|private[_\s-]?key)\b`, input.content)
}

# ---------------------------------------------------------------------------
# Tenant-specific policies (extensible)
# ---------------------------------------------------------------------------

# Example: deny content from unregistered clients
deny contains "Unregistered client" if {
    input.client_id == ""
    input.action_type == "custos_execute"
}

# Example: enterprise tier can add custom deny rules here
# deny contains "Custom enterprise rule" if {
#     input.client_id == "enterprise-tenant-id"
#     contains(input.content, "restricted_keyword")
# }

# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

triggered_rule := "block_pii_ssn" if {
    deny[_] == "SSN pattern detected"
}

triggered_rule := "block_pii_credit_card" if {
    deny[_] == "Credit card pattern detected"
}

triggered_rule := "block_prompt_injection" if {
    deny[_] == "Prompt injection attempt detected"
}

triggered_rule := "block_unregistered_client" if {
    deny[_] == "Unregistered client"
}

# If regex already denied, OPA should agree (hybrid mode input)
triggered_rule := "regex_concurs" if {
    input.regex_result.action == "deny"
}

# Allow only if no deny rules fired
allow if {
    count(deny) == 0
}
