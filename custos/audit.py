"""
CUSTOS Audit Chain

Append-only, hash-chained audit log.

Storage backends (selected via env var or constructor):
- In-memory (default): fast, no deps, resets on restart
- SQLite (AUDIT_DB_PATH env var): dev/single-node persistence
- PostgreSQL (DATABASE_URL env var): production-grade persistence
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.



import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from typing import List, Optional


# Current record-binding version. Version 0 = records emitted before trace
# binding (legacy preimage, unchanged, still verifiable). Version >= 1 = the
# request-correlation identifier (trace_id) is covered by the record hash, so
# correlation is intrinsically bound rather than merely stored alongside.
RECORD_BINDING_CURRENT = 1


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
    policy_digest: Optional[str] = None
    tenant_id: Optional[str] = None
    binding_version: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class InMemoryBackend:
    """Default backend. Fast, no dependencies. Resets on restart."""

    def save(self, record: AuditRecord) -> None:
        pass

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
                    trace_id TEXT,
                    policy_digest TEXT,
                    tenant_id TEXT,
                    binding_version INTEGER DEFAULT 0
                )
            """)
            self._migrate(conn)
            conn.commit()

    @staticmethod
    def _migrate(conn) -> None:
        """Add columns introduced after the first release, preserving rows.

        Existing databases keep their rows; new columns default to NULL/0 so
        legacy records verify exactly as before.
        """
        present = {r[1] for r in conn.execute("PRAGMA table_info(audit_records)")}
        for column, decl in (
            ("policy_digest", "TEXT"),
            ("tenant_id", "TEXT"),
            ("binding_version", "INTEGER DEFAULT 0"),
        ):
            if column not in present:
                conn.execute(f"ALTER TABLE audit_records ADD COLUMN {column} {decl}")

    def save(self, record: AuditRecord) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("""
                INSERT INTO audit_records
                (timestamp, client_id, action, triggered_rule, reason,
                 content_hash, record_hash, previous_hash, trace_id,
                 policy_digest, tenant_id, binding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.timestamp, record.client_id, record.action,
                record.triggered_rule, record.reason, record.content_hash,
                record.record_hash, record.previous_hash, record.trace_id,
                record.policy_digest, record.tenant_id,
                record.binding_version,
            ))
            conn.commit()

    def load_all(self) -> List[AuditRecord]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute("""
                SELECT timestamp, client_id, action, triggered_rule, reason,
                       content_hash, record_hash, previous_hash, trace_id,
                       policy_digest, tenant_id, binding_version
                FROM audit_records ORDER BY id ASC
            """).fetchall()
        return [
            AuditRecord(
                timestamp=r[0], client_id=r[1], action=r[2],
                triggered_rule=r[3], reason=r[4], content_hash=r[5],
                record_hash=r[6], previous_hash=r[7], trace_id=r[8],
                policy_digest=r[9], tenant_id=r[10],
                binding_version=r[11] or 0,
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
                        trace_id TEXT,
                        policy_digest TEXT,
                        tenant_id TEXT,
                        binding_version INTEGER DEFAULT 0
                    )
                """)
                for column, decl in (
                    ("policy_digest", "TEXT"),
                    ("tenant_id", "TEXT"),
                    ("binding_version", "INTEGER DEFAULT 0"),
                ):
                    cur.execute(
                        f"ALTER TABLE audit_records ADD COLUMN IF NOT EXISTS {column} {decl}"
                    )
            conn.commit()

    def save(self, record: AuditRecord) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO audit_records
                    (timestamp, client_id, action, triggered_rule, reason,
                     content_hash, record_hash, previous_hash, trace_id,
                     policy_digest, tenant_id, binding_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    record.timestamp, record.client_id, record.action,
                    record.triggered_rule, record.reason, record.content_hash,
                    record.record_hash, record.previous_hash, record.trace_id,
                    record.policy_digest, record.tenant_id,
                    record.binding_version,
                ))
            conn.commit()

    def load_all(self) -> List[AuditRecord]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT timestamp, client_id, action, triggered_rule, reason,
                           content_hash, record_hash, previous_hash, trace_id,
                           policy_digest, tenant_id, binding_version
                    FROM audit_records ORDER BY id ASC
                """)
                rows = cur.fetchall()
        return [
            AuditRecord(
                timestamp=r[0], client_id=r[1], action=r[2],
                triggered_rule=r[3], reason=r[4], content_hash=r[5],
                record_hash=r[6], previous_hash=r[7], trace_id=r[8],
                policy_digest=r[9], tenant_id=r[10],
                binding_version=r[11] or 0,
            )
            for r in rows
        ]

    def close(self) -> None:
        pass


def _build_backend(
    db_path: Optional[str] = None,
    database_url: Optional[str] = None,
):
    url = database_url or os.getenv("DATABASE_URL")
    path = db_path or os.getenv("AUDIT_DB_PATH")
    if url:
        return PostgreSQLBackend(url)
    if path:
        return SQLiteBackend(path)
    return InMemoryBackend()


def _field(record, name: str):
    """Read a record field from an AuditRecord or from its to_dict() form."""
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def preimage_fields(record, previous_hash: str) -> dict:
    """Canonical record-hash preimage.

    Single definition, used by the internal chain verifier AND by the external
    custody re-walk, so an independent consumer recomputes exactly what the
    emitter computed. Conditional fields are included only when set: legacy
    records (emitted before citations or trace binding existed) hash
    byte-identically to their original preimage and keep verifying.

    binding_version >= 1 adds the correlation identifier and a version marker
    (EABC docs/002 "Intrinsically Bound": correlation must be covered by the
    same integrity evidence as the record it correlates).
    """
    fields = {
        "timestamp": _field(record, "timestamp"),
        "client_id": _field(record, "client_id"),
        "action": _field(record, "action"),
        "triggered_rule": _field(record, "triggered_rule"),
        "reason": _field(record, "reason"),
        "content_hash": _field(record, "content_hash"),
        "previous_hash": previous_hash,
    }
    policy_digest = _field(record, "policy_digest")
    if policy_digest:
        fields["policy_digest"] = policy_digest
    tenant_id = _field(record, "tenant_id")
    if tenant_id:
        fields["tenant_id"] = tenant_id
    binding_version = _field(record, "binding_version") or 0
    if binding_version >= 1:
        fields["binding"] = f"v{binding_version}"
        trace_id = _field(record, "trace_id")
        if trace_id:
            fields["trace_id"] = trace_id
    return fields


def compute_record_hash(record, previous_hash: str) -> str:
    return hashlib.sha256(
        json.dumps(preimage_fields(record, previous_hash), sort_keys=True).encode("utf-8")
    ).hexdigest()


class AuditChain:
    GENESIS_HASH = "0" * 64

    def __init__(
        self,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
        _backend=None,
    ):
        self._records: List[AuditRecord] = []
        self._lock = threading.RLock()
        self._backend = _backend or _build_backend(db_path, database_url)
        self._db_path = db_path or os.getenv("AUDIT_DB_PATH")

        for record in self._backend.load_all():
            self._records.append(record)

    def record(
        self,
        client_id: str,
        action: str,
        reason: str,
        content: str,
        triggered_rule: Optional[str] = None,
        trace_id: Optional[str] = None,
        policy_digest: Optional[str] = None,
        tenant_id: Optional[str] = None,
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
                policy_digest=policy_digest,
                tenant_id=tenant_id,
                binding_version=RECORD_BINDING_CURRENT,
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

    def head(self) -> tuple:
        """(length, head_hash) of this chain, under the existing lock.

        Read-only snapshot for the custody anchoring path; no writes, no
        re-hashing — the hot path is untouched.
        """
        with self._lock:
            if not self._records:
                return 0, self.GENESIS_HASH
            return len(self._records), self._records[-1].record_hash

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

    @staticmethod
    def _hash_content(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_record_hash(record: AuditRecord, previous_hash: str) -> str:
        return compute_record_hash(record, previous_hash)
