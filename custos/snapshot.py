"""
CUSTOS Decision Snapshots v1.0

Exports a tamper-evident snapshot of the audit chain
for a given time range, suitable for compliance review.

The snapshot is a self-contained JSON document containing:
- All audit records in the requested range
- Chain verification result
- SHA-256 signature of the full payload
- Record count and latest hash
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Optional

from custos.audit import AuditChain


@dataclass
class SnapshotResult:
    generated_at: float
    start_time: Optional[float]
    end_time: Optional[float]
    record_count: int
    records: list
    chain_valid: bool
    chain_verification_reason: str
    latest_hash: str
    snapshot_hash: str        # SHA-256 of all fields above

    def to_dict(self) -> dict:
        return asdict(self)


class SnapshotEngine:
    """
    Generates compliance-ready snapshots of the audit chain.
    Thread-safe. Read-only — never modifies the chain.
    """

    def __init__(self, audit_chain: AuditChain):
        self._chain = audit_chain

    def generate(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> SnapshotResult:
        """
        Generate a snapshot for the given time range.
        If start_time is None, includes from genesis.
        If end_time is None, includes up to now.
        """
        now = time.time()
        effective_end = end_time if end_time is not None else now

        # Filter records by time range
        all_records = self._chain.get_records()
        filtered = [
            r for r in all_records
            if self._in_range(r["timestamp"], start_time, effective_end)
        ]

        # Verify full chain integrity
        chain_valid, chain_reason = self._chain.verify()

        # Build snapshot payload (without hash)
        payload = {
            "generated_at": now,
            "start_time": start_time,
            "end_time": effective_end,
            "record_count": len(filtered),
            "records": filtered,
            "chain_valid": chain_valid,
            "chain_verification_reason": chain_reason,
            "latest_hash": self._chain.latest_hash,
        }

        # Sign the payload
        snapshot_hash = self._sign(payload)

        return SnapshotResult(
            generated_at=now,
            start_time=start_time,
            end_time=effective_end,
            record_count=len(filtered),
            records=filtered,
            chain_valid=chain_valid,
            chain_verification_reason=chain_reason,
            latest_hash=self._chain.latest_hash,
            snapshot_hash=snapshot_hash,
        )

    def verify_snapshot(self, snapshot: dict) -> tuple[bool, str]:
        """
        Verify the integrity of a previously generated snapshot.
        Returns (True, "OK") or (False, reason).
        """
        stored_hash = snapshot.get("snapshot_hash")
        if not stored_hash:
            return False, "No snapshot_hash present"

        # Rebuild payload without the hash field
        payload = {k: v for k, v in snapshot.items() if k != "snapshot_hash"}
        expected_hash = self._sign(payload)

        if stored_hash != expected_hash:
            return False, "Snapshot hash mismatch — snapshot may have been tampered with"

        return True, "OK"

    @staticmethod
    def _in_range(
        timestamp: float,
        start: Optional[float],
        end: float,
    ) -> bool:
        if start is not None and timestamp < start:
            return False
        if timestamp > end:
            return False
        return True

    @staticmethod
    def _sign(payload: dict) -> str:
        """SHA-256 of the canonical JSON representation."""
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
