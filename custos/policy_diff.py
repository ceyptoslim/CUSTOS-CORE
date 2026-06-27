"""
CUSTOS Policy Diff v0.4

Given content and two policy rule sets, shows how the
decision differs between them.

Helps teams safely deploy new policy versions by previewing
which existing requests would be affected before going live.
"""

from dataclasses import dataclass
from typing import Optional

from custos.policy_engine import PolicyEngine, PolicyResult, PolicyRule


@dataclass
class DiffResult:
    content_preview: str           # first 100 chars only, never full content
    current_action: str
    current_triggered_rule: Optional[str]
    current_reason: str
    proposed_action: str
    proposed_triggered_rule: Optional[str]
    proposed_reason: str
    decision_changed: bool
    change_summary: str


class PolicyDiffer:
    """
    Compares policy decisions across two rule sets.
    Stateless — safe to call concurrently.
    """

    def diff(
        self,
        content: str,
        current_rules: list[PolicyRule],
        proposed_rules: list[PolicyRule],
    ) -> DiffResult:
        """
        Evaluate content against both rule sets and return a diff.
        """
        current_engine = PolicyEngine(rules=current_rules)
        proposed_engine = PolicyEngine(rules=proposed_rules)

        current_result: PolicyResult = current_engine.evaluate(content)
        proposed_result: PolicyResult = proposed_engine.evaluate(content)

        decision_changed = (
            current_result.action != proposed_result.action
            or current_result.triggered_rule != proposed_result.triggered_rule
        )

        change_summary = self._summarize(current_result, proposed_result, decision_changed)

        return DiffResult(
            content_preview=content[:100],
            current_action=current_result.action.value,
            current_triggered_rule=current_result.triggered_rule,
            current_reason=current_result.reason,
            proposed_action=proposed_result.action.value,
            proposed_triggered_rule=proposed_result.triggered_rule,
            proposed_reason=proposed_result.reason,
            decision_changed=decision_changed,
            change_summary=change_summary,
        )

    @staticmethod
    def _summarize(
        current: PolicyResult,
        proposed: PolicyResult,
        changed: bool,
    ) -> str:
        if not changed:
            return (
                f"No change — both rule sets produce "
                f"'{current.action.value}'"
            )

        return (
            f"Decision changed: '{current.action.value}' "
            f"(rule: {current.triggered_rule or 'none'}) → "
            f"'{proposed.action.value}' "
            f"(rule: {proposed.triggered_rule or 'none'})"
        )
