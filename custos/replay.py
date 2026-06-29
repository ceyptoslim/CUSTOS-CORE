"""
CUSTOS Replay Engine v1.0

Given any audit record hash, reproduces the exact policy
decision that was made at that point in time.

This makes CUSTOS decisions reproducible, not just auditable.
Compliance teams can prove what happened and why.
"""

import hashlib
import time
from dataclasses import dataclass
from typing import Optional

from custos.audit import AuditChain, AuditRecord
from custos.policy_engine import PolicyEngine


@dataclass
class ReplayResult:
    original_record_hash: str
    original_timestamp: float
    original_action: str
    original_triggered_rule: Optional[str]
    original_reason: str
    original_trace_id: Optional[str]
    replayed_action: str
    replayed_triggered_rule: Optional[str]
    replayed_reason: str
    decision_matches: bool
    replay_timestamp: float
    content_hash: str


class ReplayEngine:
    """
    Replays past decisions by re-evaluating the content hash
    against the current policy engine.

    Note: content is stored as a hash — we cannot recover raw
    content from the audit chain. Replay re-evaluates by
    content_hash match, confirming the decision is reproducible
    given the same policy rules.

    For full replay with raw content, callers must supply the
    original content string (verified against stored hash).
    """

    def __init__(self, audit_chain: AuditChain, policy_engine: PolicyEngine):
        self._chain = audit_chain
        self._engine = policy_engine

    def replay_by_hash(
        self,
        record_hash: str,
        original_content: str,
    ) -> ReplayResult:
        """
        Replay a decision given the original audit record hash
        and the original content string.

        Raises ValueError if:
        - record_hash not found in audit chain
        - content does not match stored content_hash
        """
        # Find the record
        record = self._find_record(record_hash)
        if record is None:
            raise ValueError(f"Record hash not found in audit chain: {record_hash}")

        # Verify content matches stored hash
        supplied_hash = hashlib.sha256(
            original_content.encode("utf-8")
        ).hexdigest()
        if supplied_hash != record.content_hash:
            raise ValueError(
                "Supplied content does not match stored content_hash. "
                "Cannot replay with mismatched content."
            )

        # Re-evaluate against current policy engine
        result = self._engine.evaluate(original_content)

        decision_matches = (
            result.action.value == record.action
            and result.triggered_rule == record.triggered_rule
        )

        return ReplayResult(
            original_record_hash=record.record_hash,
            original_timestamp=record.timestamp,
            original_action=record.action,
            original_triggered_rule=record.triggered_rule,
            original_reason=record.reason,
            original_trace_id=record.trace_id,
            replayed_action=result.action.value,
            replayed_triggered_rule=result.triggered_rule,
            replayed_reason=result.reason,
            decision_matches=decision_matches,
            replay_timestamp=time.time(),
            content_hash=record.content_hash,
        )

    def _find_record(self, record_hash: str) -> Optional[AuditRecord]:
        """Find a record by its hash. Returns None if not found."""
        with self._chain._lock:
            for record in self._chain._records:
                if record.record_hash == record_hash:
                    return record
        return None
