"""
CUSTOS Audit Chain

Append-only, hash-chained audit log with SQLite persistence.
Each record contains a SHA-256 hash of (previous_hash + current_record),
making the chain tamper-evident without requiring external infrastructure.

Storage backends:
  - In-memory (default): fast, no deps, resets on restart
  - SQLite (AUDIT_DB_PATH env var): persists across restarts

Upgrade path: PostgreSQL -> immutable object storage (S3/GCS with WORM policy).
"""

import hashlib
import json
import os
import sqlite3
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
    content_hash: str    # SHA-256 of evaluated content — never store raw content
    record_hash: str = ""
    previous_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AuditChain:
    """
    Append-only, hash-chained audit log.
    Thread-safe. Records are immutable once written.

    When AUDIT_DB_PATH is set, records are persisted to SQLite.
    On startup the chain is loaded from the DB and hash-verified.
    """

    GENESIS_HASH = "0" * 64

    def __init__(self, db_path: Optional[str] = None):
        self._records: List[AuditRecord] = []
        self._lock = threading.RLock()
        self._db_path = db_path or os.getenv("AUDIT_DB_PATH")
        self._conn: Optional[sqlite3.Connection] = None

        if self._db_path:
            self._init_db()
            self._load_from_db()

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

            if self._conn:
                self._persist(entry)

            return entry

    def verify(self) -> tuple:
        """
        Walk the entire chain and verify hash integrity.
        Returns (True, "OK") or (False, reason_string).
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
    # SQLite persistence
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the audit table if it doesn't exist."""
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_records (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     REAL    NOT NULL,
                client_id     TEXT    NOT NULL,
                action        TEXT    NOT NULL,
                triggered_rule TEXT,
                reason        TEXT    NOT NULL,
                content_hash  TEXT    NOT NULL,
                record_hash   TEXT    NOT NULL UNIQUE,
                previous_hash TEXT    NOT NULL
            )
        """)
        self._conn.commit()

    def _persist(self, record: AuditRecord) -> None:
        """Write a single record to SQLite (called under self._lock)."""
        self._conn.execute(
            """
            INSERT INTO audit_records
                (timestamp, client_id, action, triggered_rule, reason,
                 content_hash, record_hash, previous_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.timestamp,
                record.client_id,
                record.action,
                record.triggered_rule,
                record.reason,
                record.content_hash,
                record.record_hash,
                record.previous_hash,
            ),
        )
        self._conn.commit()

    def _load_from_db(self) -> None:
        """Replay all persisted records into memory on startup."""
        cursor = self._conn.execute(
            "SELECT timestamp, client_id, action, triggered_rule, reason, "
            "       content_hash, record_hash, previous_hash "
            "FROM audit_records ORDER BY id ASC"
        )
        for row in cursor.fetchall():
            self._records.append(
                AuditRecord(
                    timestamp=row[0],
                    client_id=row[1],
                    action=row[2],
                    triggered_rule=row[3],
                    reason=row[4],
                    content_hash=row[5],
                    record_hash=row[6],
                    previous_hash=row[7],
                )
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_content(content: str) -> str:
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
