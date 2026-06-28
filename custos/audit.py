"""
CUSTOS Audit Chain v1.0

Append-only, hash-chained audit log.

Storage backends (selected via env var or constructor):
- In-memory (default): fast, no deps, resets on restart
- SQLite (AUDIT_DB_PATH env var): dev/single-node persistence
- PostgreSQL (DATABASE_URL env var): production-grade persistence

The chain integrity model is backend-agnostic — verify() works
identically regardless of which backend is active.
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
    action: str
    triggered_rule: Optional[str]
    reason: str
    content_hash: str
    record_hash: str = ""
    previous_hash: str = ""
    trace_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

class InMemoryBackend:
    """Default backend. Fast, no dependencies. Resets on restart."""

    def save(self, record: AuditRecord) -> None:
        pass  # In-memory: records stored in AuditChain._records list only

    def load_all(self) -> List[AuditRecord]:
        return []

    def close(self) -> None:
        pass


class SQLiteBackend:
    """SQLite backend. Good for dev and single-node deployments."""

    def __init__(self, db_path: str):
        self._path = db_path
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    client_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    triggered_rule TEXT,
                    reason TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    trace_id TEXT
                )
            """)
            conn.commit()

    def save(self, record: AuditRecord) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("""
                INSERT INTO audit_records
                (timestamp, client_id, action, triggered_rule, reason,
                 content_hash, record_hash, previous_hash, trace_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.timestamp, record.client_id, record.action,
                record.triggered_rule, record.reason, record.content_hash,
                record.record_hash, record.previous_hash, record.trace_id,
            ))
            conn.commit()

    def load_all(self) -> List[AuditRecord]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute("""
                SELECT timestamp, client_id, action, triggered_rule, reason,
                       content_hash, record_hash, previous_hash, trace_id
                FROM audit_records ORDER BY id ASC
            """).fetchall()
        return [
            AuditRecord(
                timestamp=r[0], client_id=r[1], action=r[2],
                triggered_rule=r[3], reason=r[4], content_hash=r[5],
                record_hash=r[6], previous_hash=r[7], trace_id=r[8],
            )
            for r in rows
        ]

    def close(self) -> None:
        pass


class PostgreSQLBackend:
    """
    PostgreSQL backend for production deployments.
    Requires: pip install psycopg2-binary
    Connection string via DATABASE_URL env var or constructor argument.

    Example DATABASE_URL:
        postgresql://user:password@localhost:5432/custos
    """

    def __init__(self, database_url: str):
        try:
            import psycopg2
            import psycopg2.extras
            self._psycopg2 = psycopg2
        except ImportError:
            raise RuntimeError(
                "PostgreSQL backend requires psycopg2: "
                "pip install psycopg2-binary"
            )
        self._url = database_url
        self._init()

    def _connect(self):
        return self._psycopg2.connect(self._url)

    def _init(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS audit_records (
                        id SERIAL PRIMARY KEY,
                        timestamp DOUBLE PRECISION NOT NULL,
                        client_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        triggered_rule TEXT,
                        reason TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        record_hash TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        trace_id TEXT
                    )
                """)
            conn.commit()

    def save(self, record: AuditRecord) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO audit_records
                    (timestamp, client_id, action, triggered_rule, reason,
                     content_hash, record_hash, previous_hash, trace_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    record.timestamp, record.client_id, record.action,
                    record.triggered_rule, record.reason, record.content_hash,
                    record.record_hash, record.previous_hash, record.trace_id,
                ))
            conn.commit()

    def load_all(self) -> List[AuditRecord]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT timestamp, client_id, action, triggered_rule, reason,
                           content_hash, record_hash, previous_hash, trace_id
                    FROM audit_records ORDER BY id ASC
                """)
                rows = cur.fetchall()
        return [
            AuditRecord(
                timestamp=r[0], client_id=r[1], action=r[2],
                triggered_rule=r[3], reason=r[4], content_hash=r[5],
                record_hash=r[6], previous_hash=r[7], trace_id=r[8],
            )
            for r in rows
        ]

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def _build_backend(
    db_path: Optional[str] = None,
    database_url: Optional[str] = None,
):
    """Select backend based on provided config or environment variables."""
    url = database_url or os.getenv("DATABASE_URL")
    path = db_path or os.getenv("AUDIT_DB_PATH")

    if url:
        return PostgreSQLBackend(url)
    if path:
        return SQLiteBackend(path)
    return InMemoryBackend()


# ---------------------------------------------------------------------------
# AuditChain — backend-agnostic
# ---------------------------------------------------------------------------

class AuditChain:
    GENESIS_HASH = "0" * 64

    def __init__(
        self,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
        _backend=None,  # For testing — inject a backend directly
    ):
        self._records: List[AuditRecord] = []
        self._lock = threading.RLock()
        self._backend = _backend or _build_backend(db_path, database_url)
        self._db_path = db_path or os.getenv("AUDIT_DB_PATH")

        # Load existing records from backend on startup
        for record in self._backend.load_all():
            self._records.append(record)

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
        trace_id: Optional[str] = None,
    ) -> AuditRecord:
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
                trace_id=trace_id,
            )
            entry.record_hash = self._compute_record_hash(entry, previous_hash)
            self._records.append(entry)
            self._backend.save(entry)
            return entry

    def verify(self) -> tuple:
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

    @property
    def backend_type(self) -> str:
        return type(self._backend).__name__

    # ------------------------------------------------------------------
    # Hashing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_content(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_record_hash(record: AuditRecord, previous_hash: str) -> str:
        payload = json.dumps({
            "timestamp": record.timestamp,
            "client_id": record.client_id,
            "action": record.action,
            "triggered_rule": record.triggered_rule,
            "reason": record.reason,
            "content_hash": record.content_hash,
            "previous_hash": previous_hash,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
