"""
CUSTOS Audit Chain

Append-only, hash-chained audit log.
Each record contains a SHA-256 hash of (previous_hash + current_record),
making the chain tamper-evident without requiring external infrastructure.

Upgrade path: persist to SQLite -> PostgreSQL -> immutable object storage.
"""

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from typing import List, Optional


@dataclass
class AuditRecord:
    timestamp: float
    client_id: str
    action: str          # "allow" | "deny" | "audit" | "rate_limited"
    triggered_rule: Optional[str]
    reason: str
    content_hash: str    # SHA-256 of evaluated content -- never store raw content
    record_hash: str = ""
    previous_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AuditChain:
    """
    In-memory append-only audit chain.
    Thread-safe. Records are immutable once written.
    """

    GENESIS_HASH = "0" * 64  # Fixed starting hash for the chain

    def __init__(self):
        self._records: List[AuditRecord] = []
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        client_id: str,
        action: str,
        reason: str,
        content: str,
        triggered_rule: Optional[str] = None,
    ) -> AuditRecord:
        """Append a new record to the chain. Returns the finalized record."""
        with self._lock:
            previous_hash = (
                self._records[-1].record_hash if self._records else self.GENESIS_HASH
            )

            entry = AuditRecord(
                timestamp=time.time(),
                client_id=client_id,
                action=action,
                triggered_rule=triggered_rule,
                reason=reason,
                content_hash=self._hash_content(content),
                previous_hash=previous_hash,
            )
            entry.record_hash = self._compute_record_hash(entry, previous_hash)

            self._records.append(entry)
            return entry

    def verify(self) -> tuple:
        """
        Walk the entire chain and verify hash integrity.
        Returns (True, "OK") or (False, reason).
        """
        with self._lock:
            if not self._records:
                return True, "Empty chain -- OK"

            previous_hash = self.GENESIS_HASH
            for i, record in enumerate(self._records):
                if record.previous_hash != previous_hash:
                    return False, f"Chain broken at record {i}: previous_hash mismatch"

                expected = self._compute_record_hash(record, previous_hash)
                if record.record_hash != expected:
                    return False, f"Record {i} hash invalid -- tampering detected"

                previous_hash = record.record_hash

            return True, "OK"

    def get_records(self, client_id: Optional[str] = None) -> List[dict]:
        """Return all records, optionally filtered by client_id."""
        with self._lock:
            records = self._records
            if client_id:
                records = [r for r in records if r.client_id == client_id]
            return [r.to_dict() for r in records]

    @property
    def length(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def latest_hash(self) -> str:
        with self._lock:
            if not self._records:
                return self.GENESIS_HASH
            return self._records[-1].record_hash

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_content(content: str) -> str:
        """Hash raw content -- we store the hash, never the content itself."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_record_hash(record: AuditRecord, previous_hash: str) -> str:
        payload = json.dumps(
            {
                "timestamp": record.timestamp,
                "client_id": record.client_id,
                "action": record.action,
                "triggered_rule": record.triggered_rule,
                "reason": record.reason,
                "content_hash": record.content_hash,
                "previous_hash": previous_hash,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
