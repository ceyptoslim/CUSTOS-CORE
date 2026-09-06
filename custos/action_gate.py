"""
Pre-Flight Action Gate — evaluates a PROPOSED agent action BEFORE execution.

This is the action-governance layer the LORL-9.1 GovernedExecutor docstring
promises for side-effectful agents: output governance (already shipped)
judges what an agent SAID; this module judges what an agent PROPOSES TO DO,
before the consequential operation runs.

Threat model (honest scope): this gate governs agent actions inside
deployments that route through CUSTOS — tool calls, shell commands, and
their arguments. It is defense-in-depth: the network layer (egress
allowlists), the runtime layer (gVisor/Firecracker), and the OS layer remain
necessary and are NOT replaced by this module. It does NOT contain
infrastructure-level sandbox escapes and must never be claimed to.

Semantics — fail-closed everywhere:
1. Unknown tenant            -> DENY (no ungoverned evaluation, ever).
2. No tool allowlist for the  -> DENY. Deny-by-default: every tool must be
   tenant                        explicitly allowlisted; an unconfigured
                                 gate denies ALL actions.
3. Dangerous command classes  -> DENY (exfiltration, destructive, privilege,
                                 package installs, process tampering,
                                 credential access, reverse shells, and
                                 attempts to disable the governance layer
                                 itself — the "guardrail bypassing the
                                 guardrail" pattern).
4. Tenant content rules       -> the existing policy engine evaluates the
   apply to action payloads      serialized action (injection/PII/tenant
                                 pack rules all compose).
5. Every decision (allow or   -> audit record appended to the tenant's
   deny) is audited              tamper-evident chain.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from custos.policy_engine import PolicyAction, PolicyResult

if TYPE_CHECKING:  # pragma: no cover
    from custos.tenant import TenantManager


@dataclass
class ActionRequest:
    """A proposed agent action, evaluated BEFORE execution."""
    tool: str
    command: str = ""
    args: Optional[dict] = field(default=None)

    def serialize(self) -> str:
        """Single evaluation blob: tool + command + args."""
        return f"{self.tool} {self.command} {json.dumps(self.args or {}, sort_keys=True)}"


@dataclass
class ActionGateResult:
    """Decision + the audit record hash for the tamper-evident chain."""
    decision: PolicyResult
    audit_record_hash: Optional[str] = None


# (rule_name, compiled_pattern, reason) — order matters: first hit wins.
_DANGEROUS_COMMAND_RULES: list[tuple[str, "re.Pattern[str]", str]] = [
    (
        "action_cmd_reverse_shell",
        re.compile(
            r"bash\s+-i\s+>&|/dev/tcp/|nc\s+-e\s+|python3?\s+-c\s+['\"`]\s*import\s+socket"
        ),
        "Reverse shell / interactive shell exfiltration payload.",
    ),
    (
        "action_cmd_exfiltration",
        re.compile(
            r"(?i)\b(?:curl|wget|nc|ncat|netcat|scp|sftp|rsync|ftp|telnet)\b"
            r"[^\n]{0,200}(?:https?://|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b)"
        ),
        "Network egress/exfiltration command — outbound transfer attempts must be deny-by-default.",
    ),
    (
        "action_cmd_destructive",
        re.compile(
            r"(?:rm\s+-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*|rm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*"
            r"|mkfs|dd\s+if=|shred\s|>\s*/dev/sd[a-z])"
        ),
        "Destructive filesystem command.",
    ),
    (
        "action_cmd_privilege",
        re.compile(r"(?i)\b(?:sudo|doas|su\s+root)\b|chmod\s+777|chown\s+root|u\+s\b"),
        "Privilege escalation command.",
    ),
    (
        "action_cmd_package_install",
        re.compile(
            r"(?i)\b(?:pip3?|npm|yarn|apt(?:-get)?|yum|dnf|brew)\s+(?:install|i|add)\b"
        ),
        "Package installation — dependency changes must be human-approved (supply-chain vector).",
    ),
    (
        "action_cmd_process_tamper",
        re.compile(
            r"(?i)\b(?:pkill|killall)\b|kill\s+-(?:9|KILL)\b"
            r"|systemctl\s+(?:stop|disable|restart|mask)|launchctl\s+(?:unload|stop)"
        ),
        "Process/service tampering command.",
    ),
    (
        "action_cmd_credential_access",
        re.compile(
            r"(?i)(?:cat|less|more|head|tail|cp|mv|scp)\s+[^\n]{0,200}"
            r"(?:\.env\b|id_rsa|id_ed25519|\.ssh/|\.aws/|\.netrc|/etc/(?:passwd|shadow)|aws_secret|credentials)"
        ),
        "Credential/secret file access attempt.",
    ),
    (
        "action_cmd_oversight_disable",
        re.compile(
            r"(?i)\b(?:disable|bypass|uninstall|kill(?:ing)?|stop|remove|delete)\b"
            r"[^\n]{0,60}\b(?:custos|firewall|guardrail|policy\s*engine|audit\s*(?:chain|logs?|logging)|action\s*gate)\b"
        ),
        "Attempt to disable or bypass the governance layer itself — the guardrail-bypassing-the-guardrail pattern.",
    ),
]


class ActionGate:
    """Deny-by-default pre-flight gate for proposed agent actions."""

    def __init__(self, tenant_manager: "TenantManager"):
        self._tm = tenant_manager
        self._tool_allowlists: dict[str, set[str]] = {}

    def register_tools(self, tenant_id: str, tools: "set[str] | list[str]") -> None:
        """Explicitly allowlist tools for a tenant. No registration = deny all."""
        self._tool_allowlists[tenant_id] = set(tools)

    def list_tools(self, tenant_id: str) -> "set[str]":
        return set(self._tool_allowlists.get(tenant_id, set()))

    def _deny(self, rule: str, reason: str) -> PolicyResult:
        return PolicyResult(
            allowed=False,
            action=PolicyAction.DENY,
            triggered_rule=rule,
            reason=reason,
        )

    def evaluate_action(
        self,
        tenant_id: str,
        action: ActionRequest,
        client_id: str = "agent",
    ) -> ActionGateResult:
        """Evaluate a proposed action. DENY means the action must not run."""
        blob = action.serialize()

        # 1. Fail-closed: unknown tenant -> deny, no ungoverned evaluation.
        ctx = self._tm.get_strict(tenant_id)
        if ctx is None:
            decision = self._deny(
                "action_gate_unknown_tenant",
                f"Unknown tenant '{tenant_id}' — fail-closed. No ungoverned action evaluation.",
            )
            return ActionGateResult(decision=decision)

        # 2. Deny-by-default tool allowlist: unconfigured tenant denies ALL tools.
        if action.tool not in self._tool_allowlists.get(tenant_id, set()):
            decision = self._deny(
                "action_gate_tool_not_allowlisted",
                f"Tool '{action.tool}' is not in tenant '{tenant_id}'s allowlist. "
                "Deny-by-default: register tools explicitly via ActionGate.register_tools().",
            )
            record = ctx.audit_chain.record(
                client_id=client_id,
                action=decision.action.value,
                reason=decision.reason,
                content=blob,
                triggered_rule=decision.triggered_rule,
            )
            return ActionGateResult(decision=decision, audit_record_hash=record.record_hash)

        # 3. Dangerous command classes — checked BEFORE content rules.
        for rule_name, pattern, reason in _DANGEROUS_COMMAND_RULES:
            if pattern.search(blob):
                decision = self._deny(rule_name, reason)
                record = ctx.audit_chain.record(
                    client_id=client_id,
                    action=decision.action.value,
                    reason=decision.reason,
                    content=blob,
                    triggered_rule=decision.triggered_rule,
                )
                return ActionGateResult(decision=decision, audit_record_hash=record.record_hash)

        # 4. Existing content rules compose (injection, PII, tenant packs).
        decision = ctx.policy_engine.evaluate(blob)

        # 5. Audit every decision — allow or deny.
        record = ctx.audit_chain.record(
            client_id=client_id,
            action=decision.action.value,
            reason=decision.reason,
            content=blob,
            triggered_rule=decision.triggered_rule,
        )
        return ActionGateResult(decision=decision, audit_record_hash=record.record_hash)
