"""
CUSTOS Policy Store v1.1

Persistent storage for tenant policy rules.
Solves issue #20: policy customizations survive pod restarts,
Kubernetes rollouts, autoscaling, and node rescheduling.

Storage backends:
- InMemory (default): rules lost on restart, good for dev/testing
- SQLite (POLICY_DB_PATH env var): persists to local file
- PostgreSQL (DATABASE_URL env var): production-grade persistence

The PolicyStore is the single source of truth for rules.
On startup, TenantManager loads rules from the store before
serving any requests.
"""

import json
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass
from typing import List, Optional

from custos.policy_engine import PolicyAction, PolicyRule


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

class InMemoryPolicyBackend:
    """Default. Rules lost on restart."""

    def __init__(self):
        self._rules: dict[str, list[dict]] = {}
        self._lock = threading.RLock()

    def save_rules(self, tenant_id: str, rules: List[PolicyRule]) -> None:
        with self._lock:
            self._rules[tenant_id] = [_rule_to_dict(r) for r in rules]

    def load_rules(self, tenant_id: str) -> List[PolicyRule]:
        with self._lock:
            raw = self._rules.get(tenant_id, [])
            return [_rule_from_dict(r) for r in raw]

    def delete_tenant(self, tenant_id: str) -> None:
        with self._lock:
            self._rules.pop(tenant_id, None)

    def list_tenants(self) -> List[str]:
        with self._lock:
            return list(self._rules.keys())


class SQLitePolicyBackend:
    """SQLite backend. Persists rules across restarts."""

    def __init__(self, db_path: str):
        self._path = db_path
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS policy_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    UNIQUE(tenant_id, name)
                )
            """)
            conn.commit()

    def save_rules(self, tenant_id: str, rules: List[PolicyRule]) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "DELETE FROM policy_rules WHERE tenant_id = ?", (tenant_id,)
            )
            for rule in rules:
                conn.execute("""
                    INSERT INTO policy_rules (tenant_id, name, pattern, action, reason)
                    VALUES (?, ?, ?, ?, ?)
                """, (tenant_id, rule.name, rule.pattern, rule.action.value, rule.reason))
            conn.commit()

    def load_rules(self, tenant_id: str) -> List[PolicyRule]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute("""
                SELECT name, pattern, action, reason
                FROM policy_rules WHERE tenant_id = ?
                ORDER BY id ASC
            """, (tenant_id,)).fetchall()
        return [
            PolicyRule(
                name=r[0], pattern=r[1],
                action=PolicyAction(r[2]), reason=r[3],
            )
            for r in rows
        ]

    def delete_tenant(self, tenant_id: str) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "DELETE FROM policy_rules WHERE tenant_id = ?", (tenant_id,)
            )
            conn.commit()

    def list_tenants(self) -> List[str]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT tenant_id FROM policy_rules"
            ).fetchall()
        return [r[0] for r in rows]


class PostgreSQLPolicyBackend:
    """
    PostgreSQL backend for production deployments.
    Requires psycopg2-binary. Connection via DATABASE_URL env var.
    """

    def __init__(self, database_url: str):
        try:
            import psycopg2
            self._psycopg2 = psycopg2
        except ImportError:
            raise RuntimeError(
                "PostgreSQL backend requires psycopg2: pip install psycopg2-binary"
            )
        self._url = database_url
        self._init()

    def _connect(self):
        return self._psycopg2.connect(self._url)

    def _init(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS policy_rules (
                        id SERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        pattern TEXT NOT NULL,
                        action TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        UNIQUE(tenant_id, name)
                    )
                """)
            conn.commit()

    def save_rules(self, tenant_id: str, rules: List[PolicyRule]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM policy_rules WHERE tenant_id = %s", (tenant_id,)
                )
                for rule in rules:
                    cur.execute("""
                        INSERT INTO policy_rules (tenant_id, name, pattern, action, reason)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (tenant_id, rule.name, rule.pattern, rule.action.value, rule.reason))
            conn.commit()

    def load_rules(self, tenant_id: str) -> List[PolicyRule]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, pattern, action, reason
                    FROM policy_rules WHERE tenant_id = %s
                    ORDER BY id ASC
                """, (tenant_id,))
                rows = cur.fetchall()
        return [
            PolicyRule(
                name=r[0], pattern=r[1],
                action=PolicyAction(r[2]), reason=r[3],
            )
            for r in rows
        ]

    def delete_tenant(self, tenant_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM policy_rules WHERE tenant_id = %s", (tenant_id,)
                )
            conn.commit()

    def list_tenants(self) -> List[str]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT tenant_id FROM policy_rules")
                rows = cur.fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def _build_policy_backend(
    db_path: Optional[str] = None,
    database_url: Optional[str] = None,
):
    url = database_url or os.getenv("DATABASE_URL")
    path = db_path or os.getenv("POLICY_DB_PATH")

    if url:
        return PostgreSQLPolicyBackend(url)
    if path:
        return SQLitePolicyBackend(path)
    return InMemoryPolicyBackend()


# ---------------------------------------------------------------------------
# PolicyStore — public interface
# ---------------------------------------------------------------------------

class PolicyStore:
    """
    Persistent policy rule storage.
    Thread-safe. Backend-agnostic.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
        _backend=None,
    ):
        self._backend = _backend or _build_policy_backend(db_path, database_url)

    def save(self, tenant_id: str, rules: List[PolicyRule]) -> None:
        """Persist all rules for a tenant. Replaces any existing rules."""
        self._backend.save_rules(tenant_id, rules)

    def load(self, tenant_id: str) -> List[PolicyRule]:
        """Load all rules for a tenant. Returns empty list if none stored."""
        return self._backend.load_rules(tenant_id)

    def delete(self, tenant_id: str) -> None:
        """Remove all rules for a tenant."""
        self._backend.delete_tenant(tenant_id)

    def list_tenants(self) -> List[str]:
        """Return all tenant IDs that have stored rules."""
        return self._backend.list_tenants()

    @property
    def backend_type(self) -> str:
        return type(self._backend).__name__


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _rule_to_dict(rule: PolicyRule) -> dict:
    return {
        "name": rule.name,
        "pattern": rule.pattern,
        "action": rule.action.value,
        "reason": rule.reason,
    }


def _rule_from_dict(d: dict) -> PolicyRule:
    return PolicyRule(
        name=d["name"],
        pattern=d["pattern"],
        action=PolicyAction(d["action"]),
        reason=d["reason"],
    )
