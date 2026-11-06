"""Whether the audit chain this process serves can survive the process.

The served path built every tenant's chain with a bare `AuditChain()`, so no
configuration made the API's records durable: SQLite and PostgreSQL backends
existed and were tested, and nothing in the request path could reach either.
That is now resolved from one place, and production refuses rather than serving
records that are described as an audit trail and lost on restart.
"""

import os
from typing import Optional

#: Backend names that keep nothing after the process exits.
EPHEMERAL_BACKENDS = ("inmemorybackend",)


class AuditPersistenceRefused(RuntimeError):
    """The declared environment cannot be backed by the audit store in force."""


def _normalise(backend_type: str) -> str:
    return (backend_type or "").replace("-", "").replace("_", "").lower()


def is_durable(backend_type: str) -> bool:
    return _normalise(backend_type) not in EPHEMERAL_BACKENDS


def audit_store_source() -> str:
    """Where the store configuration came from, named rather than inferred.

    Same precedence the backend builder uses, reported so an operator can tell
    which variable is in force instead of guessing at two of them.
    """
    if os.getenv("DATABASE_URL"):
        return "DATABASE_URL"
    if os.getenv("AUDIT_DB_PATH"):
        return "AUDIT_DB_PATH"
    return "none"


def require_durable_audit(
    backend_type: str, env: Optional[str] = None
) -> dict:
    """Refuse production on an audit store that cannot outlive the process.

    Refusing is the honest option: the alternative is a production build whose
    `/v1/info` names a backend and whose records vanish on deploy, with nothing
    in the response saying which. Non-production keeps the in-memory default,
    because a development process that has to provision a database to run a
    test is a process people stop running.
    """
    environment = (env if env is not None else os.getenv("CUSTOS_ENV", "development"))
    environment = (environment or "development").lower()
    durable = is_durable(backend_type)
    summary = {
        "audit_backend": backend_type,
        "audit_durable": durable,
        "audit_store_source": audit_store_source(),
        "environment": environment,
    }

    if environment == "production" and not durable:
        source = summary["audit_store_source"]
        if source != "none":
            # A store is configured and the chain in force is not using it.
            # Saying "set a variable you already set" would send an operator to
            # look in the wrong place, so this anomaly gets its own reason.
            raise AuditPersistenceRefused(
                f"{source} is set but the chain in force is {backend_type}. The "
                "store configuration was read before the variable was, so the "
                "chain was built in-memory anyway. Configure the store in the "
                "process environment (before import) rather than at runtime."
            )
        raise AuditPersistenceRefused(
            "CUSTOS_ENV=production with audit_backend="
            f"{backend_type}, which keeps no records once this process exits. "
            "A production process must not serve an audit trail it cannot keep. "
            "Set AUDIT_DB_PATH (SQLite) or DATABASE_URL (PostgreSQL) so the "
            "records survive a restart, or unset CUSTOS_ENV to run as "
            "development. This refusal exists because the alternative is a "
            "service that reports a backend and loses the records it names."
        )

    if durable:
        summary["audit_durability_note"] = (
            "records survive this process; per-tenant scoping keeps each "
            "tenant's chain separate"
        )
    else:
        summary["audit_durability_note"] = (
            "records do not survive a restart, and the previous_hash constraint "
            "that prevents a forked chain does not apply, because no store is "
            "shared. Development default, refused in production."
        )

    return summary
